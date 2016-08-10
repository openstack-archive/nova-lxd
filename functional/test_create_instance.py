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

import uuid

from shade import exc

from functional.base import FunctionalTestCase


class LXDTestCreateInstance(FunctionalTestCase):

    def test_create_instance(self):
        instance_name = uuid.uuid1()
        self.addCleanup(self._cleanup_server, instance_name)
        self.create_image('lxd')
        instance = self.create_instance('lxd', instance_name)
        output = self.run_command(instance['accessIPv4'], 'uptime')
        self.assertTrue('load' in output)

    def test_delete_instance(self):
        instance_name = uuid.uuid1()
        self.addCleanup(self._cleanup_server, instance_name)
        self.create_image('lxd')
        instance = self.create_instance('lxd', instance_name)
        self.delete_instance(instance.id)
        self.assertFalse(instance_name in
                         [inst.name for inst in self.cloud.list_servers()])

    def test_create_instance_invalid_qcow2(self):
        instance_name = uuid.uuid1()
        self.addCleanup(self._cleanup_server, instance_name)
        self.create_image('lxd-qcow2', disk_format='qcow2')
        self.assertRaises(exc.OpenStackCloudException,
                          self.create_instance, 'lxd-qcow2', instance_name)
        self.cloud.delete_image('lxd-qcow2')

    def test_create_instnace_invalid_iso_format(self):
        instance_name = uuid.uuid1()
        self.addCleanup(self._cleanup_server, instance_name)
        self.create_image('lxd-iso', disk_format='iso')
        self.assertRaises(exc.OpenStackCloudException,
                          self.create_instance, 'lxd-iso', instance_name)
        self.cloud.delete_image('lxd-iso')

    def test_create_instance_verify_vcpu(self):
        instance_name = uuid.uuid1()
        self.addCleanup(self._cleanup_server, instance_name)
        self.create_image('lxd')
        instance = self.create_instance('lxd', instance_name)
        cmd = 'grep -c ^processor /proc/cpuinfo'
        output = self.run_command(instance['accessIPv4'], cmd)
        self.assertEqual(output.strip(), '1')

    def _cleanup_server(self, server_name):
        server = self.cloud.get_server(server_name)
        self.cloud.delete_server(server.name, wait=True)
