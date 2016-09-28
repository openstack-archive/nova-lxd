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

from pylxd import client

from tempest.api.compute import base
from tempest.common.utils import data_utils
from tempest import config

CONF = config.CONF


class LXDServersTestJSON(base.BaseV2ComputeAdminTest):
    disk_config = 'AUTO'

    def __init__(self, *args, **kwargs):
        super(LXDServersTestJSON, self).__init__(*args, **kwargs)
        self.client = client.Client()

    @classmethod
    def setup_credentials(cls):
        cls.prepare_instance_network()
        super(LXDServersTestJSON, cls).setup_credentials()

    @classmethod
    def setup_clients(cls):
        super(LXDServersTestJSON, cls).setup_clients()
        cls.client = cls.os_adm.servers_client
        cls.flavors_client = cls.os_adm.flavors_client

    @classmethod
    def resource_setup(cls):
        cls.set_validation_resources()
        super(LXDServersTestJSON, cls).resource_setup()
        cls.meta = {'hello': 'world'}
        cls.accessIPv4 = '1.1.1.1'
        cls.accessIPv6 = '0000:0000:0000:0000:0000:babe:220.12.22.2'
        cls.name = data_utils.rand_name(cls.__name__ + '-server')
        cls.password = data_utils.rand_password()
        disk_config = cls.disk_config
        cls.server_initial = cls.create_test_server(
            validatable=True,
            wait_until='ACTIVE',
            name=cls.name,
            metadata=cls.meta,
            accessIPv4=cls.accessIPv4,
            accessIPv6=cls.accessIPv6,
            disk_config=disk_config,
            adminPass=cls.password)
        cls.server = (
            cls.client.show_server(cls.server_initial['id'])['server'])

    def test_profile_configuration(self):
        # Verify that the profile was created
        profile = self.client.profiles.get(
            self.server['OS-EXT-SRV-ATTR:instance_name'])

        self.assertEqual(
            self.server['OS-EXT-SRV-ATTR:instance_name'], profile.name)

        self.assertIn('raw.lxc', profile.config)
        self.assertIn('boot.autostart', profile.config)
        self.assertIn('limits.cpu', profile.config)
        self.assertIn('limits.memory', profile.config)

        self.assertIn('root', profile.devices)

    def test_verify_created_server_vcpus(self):
        # Verify that the number of vcpus reported by the instance matches
        # the amount stated by the flavor
        flavor = self.flavors_client.show_flavor(self.flavor_ref)['flavor']

        profile = self.client.profiles.get(
            self.server['OS-EXT-SRV-ATTR:instance_name'])
        self.assertEqual(
            '%s' % flavor['vcpus'], profile.config['limits.cpu'])

    def test_verify_created_server_memory(self):
        # Verify that the memory reported by the instance matches
        # the amount stated by the flavor
        flavor = self.flavors_client.show_flavor(self.flavor_ref)['flavor']

        profile = self.client.profiles.get(
            self.server['OS-EXT-SRV-ATTR:instance_name'])
        self.assertEqual(
            '%sMB' % flavor['ram'], profile.config['limits.memory'])

    def test_verify_server_root_size(self):
        flavor = self.flavors_client.show_flavor(self.flavor_ref)['flavor']

        profile = self.client.profiles.get(
            self.server['OS-EXT-SRV-ATTR:instance_name'])
        self.assertEqual(
            '%sGB' % flavor['disk'], profile.devices['root']['size'])

    def test_verify_console_log(self):
        # Verify that the console log for the container exists
        profile = self.client.profiles.get(
            self.server['OS-EXT-SRV-ATTR:instance_name'])
        self.assertIn('lxc.console.logfile', profile.config['raw.lxc'])

    def test_verify_network_configuration(self):
        # Verify network is configured for the instance
        profile = self.client.profiles.get(
            self.server['OS-EXT-SRV-ATTR:instance_name'])
        for device in profile.devices:
            if 'root' not in device:
                network_device = device
        self.assertEqual('nic', profile.devices[network_device]['type'])
        self.assertEqual('bridged', profile.devices[network_device]['nictype'])
        self.assertEqual(
            network_device, profile.devices[network_device]['parent'])

    def test_container_configuration_valid(self):
        # Verify container configuration is correct
        profile = self.client.profiles.get(
            self.server['OS-EXT-SRV-ATTR:instance_name'])
        container = self.client.containers.get(
            self.server['OS-EXT-SRV-ATTR:instance_name'])
        flavor = self.flavors_client.show_flavor(self.flavor_ref)['flavor']

        self.assertEqual(profile.name, container.profiles[0])
        self.assertIn('raw.lxc', container.expanded_config)
        self.assertEqual(
            '%s' % flavor['vcpus'], container.expanded_config['limits.cpu'])
        self.assertEqual(
            '%sMB' % flavor['ram'], container.expanded_config['limits.memory'])

        self.assertEqual(
            '%sGB' % flavor['disk'],
            container.expanded_devices['root']['size'])

        for device in profile.devices:
            if 'root' not in device:
                network_device = device
        self.assertIn(network_device, container.expanded_devices)
        self.assertEqual(
            'nic', container.expanded_devices[network_device]['type'])
        self.assertEqual(
            'bridged', container.expanded_devices[network_device]['nictype'])
        self.assertEqual(
            network_device,
            container.expanded_devices[network_device]['parent'])
