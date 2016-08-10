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

from base import FunctionalTestCase


class LXDTestServerActions(FunctionalTestCase):

    def test_reboot_instance(self):
        self.create_image('lxd')
        instance_name = uuid.uuid1()
        instance = self.create_instance('lxd', instance_name)
        self.nova.servers.reboot(instance.id)
        self.cloud.wait_for_server(instance)
        self.wait_for_ssh(instance)
        output = self.run_command(instance['accessIPv4'], 'last reboot -x')
        self.assertTrue('reboot' in output)
        self.delete_instance(instance.id)

    def test_reboot_stop_instance(self):
        self.create_image('lxd')
        instance_name = uuid.uuid1()
        instance = self.create_instance('lxd', instance_name)
        self.cloud.wait_for_server(instance)
        self.nova.servers.reboot(instance.id)
        self.cloud.wait_for_server(instance)
        self.wait_for_ssh(instance)
        output = self.run_command(instance['accessIPv4'], 'last reboot -x')
        self.assertTrue('reboot' in output)
        self.nova.servers.stop(instance.id)
        status = self.wait_for_instance_status(
            instance, ('ACTIVE', 'SHUTOFF'), 5, 10)
        self.assertTrue(status)
        self.delete_instance(instance.id)

    def test_reboot_pause_instnace(self):
        self.create_image('lxd')
        instance_name = uuid.uuid1()
        instance = self.create_instance('lxd', instance_name)
        self.cloud.wait_for_server(instance)
        self.nova.servers.reboot(instance.id)
        self.cloud.wait_for_server(instance)
        self.wait_for_ssh(instance)
        output = self.run_command(instance['accessIPv4'], 'last reboot -x')
        self.assertTrue('reboot' in output)
        self.nova.servers.stop(instance.id)
        status = self.wait_for_instance_status(
            instance, ('ACTIVE', 'SHUTOFF'), 5, 10)
        self.assertTrue(status)
        self.delete_instance(instance.id)

    def test_reboot_suspend_instance(self):
        self.create_image('lxd')
        instance_name = uuid.uuid1()
        instance = self.create_instance('lxd', instance_name)
        self.cloud.wait_for_server(instance)
        self.nova.servers.reboot(instance.id)
        self.cloud.wait_for_server(instance)
        self.wait_for_ssh(instance)
        output = self.run_command(instance['accessIPv4'], 'last reboot -x')
        self.assertTrue('reboot' in output)
        self.nova.servers.suspend(instance.id)
        status = self.wait_for_instance_status(
            instance, ('ACTIVE', 'SUSPENDED'), 5, 10)
        self.assertTrue(status)
        self.delete_instance(instance.id)

    def test_stop_and_start_server(self):
        self.create_image('lxd')
        self.create_keypair('testkey')
        instance_name = uuid.uuid1()
        instance = self.create_instance('lxd', instance_name)
        self.cloud.wait_for_server(instance)
        self.nova.servers.stop(instance.id)
        status = self.wait_for_instance_status(
            instance, ('ACTIVE', 'SHUTDOWN'), 5, 10)
        self.assertTrue(status)
        status = self.wait_for_instance_status(
            instance, ('SHUTDOWN', 'ACTIVE'), 5, 10)
        self.assertTrue(status)
        self.delete_instance(instance.id)

    def test_pause_and_unpause_server(self):
        self.create_image('lxd')
        self.create_keypair('testkey')
        instance_name = uuid.uuid1()
        instance = self.create_instance('lxd', instance_name)
        self.cloud.wait_for_server(instance)
        self.nova.servers.pause(instance.id)
        status = self.wait_for_instance_status(
            instance, ('ACTIVE', 'PAUSED'), 5, 10)
        self.assertTrue(status)
        status = self.wait_for_instance_status(
            instance, ('PAUSED', 'ACTIVE'), 5, 10)
        self.assertTrue(status)
        self.delete_instance(instance.id)

    def test_suspend_and_resume_server(self):
        self.create_image('lxd')
        self.create_keypair('testkey')
        instance_name = uuid.uuid1()
        instance = self.create_instance('lxd', instance_name)
        self.cloud.wait_for_server(instance)
        self.nova.servers.suspend(instance.id)
        status = self.wait_for_instance_status(
            instance, ('ACTIVE', 'SUSPENDED'), 5, 10)
        self.assertTrue(status)
        status = self.wait_for_instance_status(
            instance, ('SUSPENDED', 'ACTIVE'), 5, 10)
        self.assertTrue(status)
        self.delete_instance(instance.id)

    def test_get_console_output(self):
        self.create_image('lxd')
        self.create_keypair('testkey')
        instance_name = uuid.uuid1()
        instance = self.create_instance('lxd', instance_name)
        server = self.nova.servers.get(instance.id)
        output = server.get_console_output()
        self.assertTrue('BEGIN SSH HOST KEY KEYS' in output)
        self.delete_instance(instance.id)
