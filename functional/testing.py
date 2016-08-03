import unittest
import subprocess
import time
import urllib
import os

import os_client_config

import shade
from shade import exc

LXD_IMAGE_URL = 'http://cloud-images.ubuntu.com/trusty/current/trusty-server-cloudimg-amd64-root.tar.gz'

class FunctionalTestCase(unittest.TestCase):
    
    def setUp(self):
        super(FunctionalTestCase, self).setUp()

        self.cloud = shade.openstack_cloud(cloud='devstack')

        config = os_client_config.OpenStackConfig()
        cloud_config = config.get_one_cloud(cloud='devstack')
        self.nova = cloud_config.get_legacy_client('compute')

        self.keypair = 'zil-key'

        self.image = self.create_image('lxd')
        self.flavor = self.cloud.get_flavor_by_ram(64)
        self.create_keypair()

    def create_image(self, lxd_name, disk_format='raw'):
        image = self.cloud.get_image(lxd_name)
        if image:
            return image

        http_proxy = os.getenv('AMULET_HTTP_PROXY')
        if http_proxy:
            proxies = {'http': http_proxy}
            opener = urllib.FancyURLopener(proxies)
        else:
            opener = urllib.FancyURLopener()

        abs_file_name = lxd_name
        if not os.path.exists(abs_file_name):
            opener.retrieve(LXD_IMAGE_URL, abs_file_name)

        return self.cloud.create_image(
            lxd_name, filename=abs_file_name, container_format='bare',
            disk_format=disk_format)

    def create_keypair(self):
        ssh_directory = '/tmp/.ssh'
        if not os.path.isdir(ssh_directory):
            os.mkdir(ssh_directory)
            subprocess.call(
                ['ssh-keygen', '-t', 'rsa', '-N', '', '-f',
                '%s/id_rsa_zil' % ssh_directory])

            with open('%s/id_rsa_zil.pub' % ssh_directory) as f:
                key_content = f.read()
                self.cloud.create_keypair('testkey', key_content)

    def wait_for_instance_status(self, server_id, status, timeout=3600):
        for count in self._iterate_timeout(
                timeout,
                'Timeout waiting for instance statue'):
            try:
                server = self.nova.servers.get(server_id)
            except Exception:
                continue
            if not server:
                continue

            if server.status == status:
                return status
            elif server.status == 'ERROR':
                raise Exception('error raised')

    def _iterate_timeout(self, timeout, message, wait=2):
        try:
            wait = float(wait)
        except ValueError:
            print "Wait must be an int or float"
            raise

        start = time.time()
        count = 0
        while (timeout is None) or (time.time() < start + timeout):
            count += 1
            yield count
            time.sleep(wait)
        raise Exception(mesage)
