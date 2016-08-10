# Copyright 2016 Canonical Ltd
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import unittest
import subprocess
import time
import tempfile
import socket
import urllib
import os

import os_client_config
import paramiko
import shade

LXD_IMAGE_URL = \
    'http://cloud-images.ubuntu.com/trusty/current/trusty-server-cloudimg-amd64-root.tar.gz'  # noqa


class FunctionalTestCase(unittest.TestCase):

    def setUp(self):
        super(FunctionalTestCase, self).setUp()

        self.key_name = 'testkey'
        self.ssh_dir = '/tmp/.ssh'

        self.cloud = os_client_config.make_shade()
        self.config = os_client_config.OpenStackConfig()
        cloud_config = self.config.get_one_cloud(cloud='envvars')
        self.nova = cloud_config.get_legacy_client('compute')

        operator_config = self.config.get_one_cloud(coud='envvars')
        self.operator = shade.OperatorCloud(
            cloud_config=operator_config)

        # Setup flavors
        flavor = self.cloud.get_flavor('m1.tiny')
        if not flavor:
            flavor_name = 'm1.tiny'
            flavor_kwargs = dict(
                name=flavor_name, ram=512, vcpus=1, disk=1, ephemeral=0,
                swap=0, rxtx_factor=1.0, is_public=True)
            self.operator.create_flavor(**flavor_kwargs)

        flavor = self.cloud.get_flavor('m1.lxc')
        if not flavor:
            flavor_name = 'm1.lxc'
            flavor_kwargs = dict(
                name=flavor_name, ram=512, vcpus=1, disk=1, ephemeral=1,
                swap=0, rxtx_factor=1.0, is_public=True)
            self.operator.create_flavor(**flavor_kwargs)

        self.tempdir = None
        self.create_keypair()
        self.addCleanup(self._cleanup_test)

    def _cleanup_test(self):
        self.operator.delete_flavor('m1.lxc')

    def create_image(self, lxd_name, disk_format='raw'):
        image = self.cloud.get_image(lxd_name)
        if image:
            return

        self.tempdir = tempfile.mkdtemp()

        http_proxy = os.getenv('AMULET_HTTP_PROXY')
        if http_proxy:
            proxies = {'http': http_proxy}
            opener = urllib.FancyURLopener(proxies)
        else:
            opener = urllib.FancyURLopener()

        base_image = os.path.join(self.tempdir, 'lxd')
        if not os.path.exists(base_image):
            opener.retrieve(LXD_IMAGE_URL, base_image)

        return self.cloud.create_image(
            lxd_name, filename=base_image, container_format='bare',
            disk_format=disk_format)

    def create_keypair(self, ssh_dir=None, key_name=None):
        if self.cloud.search_keypairs(key_name):
            return

        self.tempdir = tempfile.mkdtemp()

        if key_name is None:
            key_name = self.key_name
        if ssh_dir is None:
            ssh_dir = self.ssh_dir

        if not os.path.isdir(ssh_dir):
            os.mkdir(ssh_dir)

            key_file = os.path.join(ssh_dir, key_name)

            subprocess.call(
                ['ssh-keygen', '-t', 'rsa', '-N', '', '-f',
                 '%s' % key_file])
            with open(key_file + '.pub') as f:
                key_content = f.read()
            self.cloud.create_keypair(key_name, key_content)

    def create_instance(self, image_name, instance_name,
                        flavor='m1.tiny', sec_group='zil-test', key_name=None):

        if not self.cloud.search_security_groups(sec_group):
            self.cloud.create_security_group(
                sec_group, 'network access for functional testing.')
            self.cloud.create_security_group_rule(sec_group, 22, 22, 'TCP')
            self.cloud.create_security_group_rule(sec_group, -1, -1, 'ICMP')

        if key_name is None:
            key_name = self.key_name

        flavor = self.cloud.get_flavor(flavor)
        if flavor is None:
            self.assertFalse('No sensible flavor found')

        image = self.cloud.get_image(image_name)
        if flavor is None:
            self.assertFalse('No sensibleimageisfound')

        instance = self.cloud.create_server(wait=True, auto_ip=True,
                                            name=instance_name,
                                            image=image.id,
                                            flavor=flavor.id,
                                            key_name=key_name,
                                            network='private',
                                            security_groups=[sec_group])

        self.wait_for_ssh(instance)

        return instance

    def delete_instance(self, instance):
        self.cloud.delete_server(instance, wait=False, delete_ips=True)

    def run_command(self, host, command, key_file=None):
        if not key_file:
            key_file = os.path.join(self.ssh_dir, self.key_name)
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.WarningPolicy())
        client.connect(host, username='ubuntu', key_filename=key_file,
                       banner_timeout=60.0)
        stdin, stdout, stderr = client.exec_command(command)
        stdin.close()
        return stdout.read()

    def wait_for_ssh(self, instance):
        num_retries = 0
        while not self.check_host_availability(instance['accessIPv4'],
                                               timeout=6) or num_retries == 5:
            num_retries += 1

    def wait_for_instance_status(self, instance, status_list, retry, sleep):
        if not instance:
            return False

        while instance.status not in status_list and retry:
            time.sleep(sleep)
            instance = self.nova.servers.get(instance.id)
            retry -= 1
        return instance.status in status_list

    def check_host_availability(self, host, timeout, user='ubuntu'):
        key_file = os.path.join(self.ssh_dir, self.key_name)
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.WarningPolicy())
        try:
            client.connect(host, username='ubuntu', key_filename=key_file)
            return True
        except (paramiko.BadHostKeyException, paramiko.AuthenticationException,
                paramiko.SSHException, socket.error):
            time.sleep(timeout)
            return False
