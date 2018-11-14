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
import mock
from nova import context
from nova import exception
from nova import test
from nova.network import model as network_model
from nova.tests.unit import fake_instance

from nova.virt.lxd import flavor


class ToProfileTest(test.NoDBTestCase):
    """Tests for nova.virt.lxd.flavor.to_profile."""

    def setUp(self):
        super(ToProfileTest, self).setUp()
        self.client = mock.Mock()
        self.client.host_info = {
            'api_extensions': [],
            'environment': {
                'storage': 'zfs'
            }
        }

        self.patchers = []
        CONF_patcher = mock.patch('nova.virt.lxd.driver.nova.conf.CONF')
        self.patchers.append(CONF_patcher)
        self.CONF = CONF_patcher.start()
        self.CONF.instances_path = '/i'
        self.CONF.lxd.root_dir = ''

        CONF_patcher = mock.patch('nova.virt.lxd.flavor.CONF')
        self.patchers.append(CONF_patcher)
        self.CONF2 = CONF_patcher.start()
        self.CONF2.lxd.pool = None
        self.CONF2.lxd.root_dir = ''

    def tearDown(self):
        super(ToProfileTest, self).tearDown()
        for patcher in self.patchers:
            patcher.stop()

    def test_to_profile(self):
        """A profile configuration is requested of the LXD client."""
        ctx = context.get_admin_context()
        instance = fake_instance.fake_instance_obj(
            ctx, name='test', memory_mb=0)
        network_info = []
        block_info = []

        expected_config = {
            'environment.product_name': 'OpenStack Nova',
            'limits.cpu': '1',
            'limits.memory': '0MB',
            'raw.lxc': (
                'lxc.console.logfile=/var/log/lxd/{}/console.log\n'.format(
                    instance.name)),
        }
        expected_devices = {
            'root': {
                'path': '/',
                'size': '0GB',
                'type': 'disk'
            },
        }

        flavor.to_profile(self.client, instance, network_info, block_info)

        self.client.profiles.create.assert_called_once_with(
            instance.name, expected_config, expected_devices)

    def test_to_profile_lvm(self):
        """A profile configuration is requested of the LXD client."""
        self.client.host_info['environment']['storage'] = 'lvm'
        ctx = context.get_admin_context()
        instance = fake_instance.fake_instance_obj(
            ctx, name='test', memory_mb=0)
        network_info = []
        block_info = []

        expected_config = {
            'environment.product_name': 'OpenStack Nova',
            'limits.cpu': '1',
            'limits.memory': '0MB',
            'raw.lxc': (
                'lxc.console.logfile=/var/log/lxd/{}/console.log\n'.format(
                    instance.name)),
        }
        expected_devices = {
            'root': {
                'path': '/',
                'type': 'disk'
            },
        }

        flavor.to_profile(self.client, instance, network_info, block_info)

        self.client.profiles.create.assert_called_once_with(
            instance.name, expected_config, expected_devices)

    def test_storage_pools(self):
        self.client.host_info['api_extensions'].append('storage')
        self.CONF2.lxd.pool = 'test_pool'
        ctx = context.get_admin_context()
        instance = fake_instance.fake_instance_obj(
            ctx, name='test', memory_mb=0)
        network_info = []
        block_info = []
        expected_config = {
            'environment.product_name': 'OpenStack Nova',
            'limits.cpu': '1',
            'limits.memory': '0MB',
            'raw.lxc': (
                'lxc.console.logfile=/var/log/lxd/{}/console.log\n'.format(
                    instance.name))
        }
        expected_devices = {
            'root': {
                'path': '/',
                'type': 'disk',
                'pool': 'test_pool',
            },
        }
        flavor.to_profile(self.client, instance, network_info, block_info)

        self.client.profiles.create.assert_called_once_with(
            instance.name, expected_config, expected_devices)

    def test_to_profile_security(self):
        self.client.host_info['api_extensions'].append('id_map')

        ctx = context.get_admin_context()
        instance = fake_instance.fake_instance_obj(
            ctx, name='test', memory_mb=0)
        instance.flavor.extra_specs = {
            'lxd:nested_allowed': True,
            'lxd:privileged_allowed': True,
        }
        network_info = []
        block_info = []

        expected_config = {
            'environment.product_name': 'OpenStack Nova',
            'limits.cpu': '1',
            'limits.memory': '0MB',
            'raw.lxc': (
                'lxc.console.logfile=/var/log/lxd/{}/console.log\n'.format(
                    instance.name)),
            'security.nesting': 'True',
            'security.privileged': 'True',
        }
        expected_devices = {
            'root': {
                'path': '/',
                'size': '0GB',
                'type': 'disk'
            },
        }

        flavor.to_profile(self.client, instance, network_info, block_info)

        self.client.profiles.create.assert_called_once_with(
            instance.name, expected_config, expected_devices)

    def test_to_profile_idmap(self):
        self.client.host_info['api_extensions'].append('id_map')

        ctx = context.get_admin_context()
        instance = fake_instance.fake_instance_obj(
            ctx, name='test', memory_mb=0)
        instance.flavor.extra_specs = {
            'lxd:isolated': True,
        }
        network_info = []
        block_info = []

        expected_config = {
            'environment.product_name': 'OpenStack Nova',
            'security.idmap.isolated': 'True',
            'limits.cpu': '1',
            'limits.memory': '0MB',
            'raw.lxc': (
                'lxc.console.logfile=/var/log/lxd/{}/console.log\n'.format(
                    instance.name)),
        }
        expected_devices = {
            'root': {
                'path': '/',
                'size': '0GB',
                'type': 'disk'
            },
        }

        flavor.to_profile(self.client, instance, network_info, block_info)

        self.client.profiles.create.assert_called_once_with(
            instance.name, expected_config, expected_devices)

    def test_to_profile_idmap_unsupported(self):
        ctx = context.get_admin_context()
        instance = fake_instance.fake_instance_obj(
            ctx, name='test', memory_mb=0)
        instance.flavor.extra_specs = {
            'lxd:isolated': True,
        }
        network_info = []
        block_info = []

        self.assertRaises(
            exception.NovaException,
            flavor.to_profile, self.client, instance, network_info, block_info)

    def test_to_profile_quota_extra_specs_bytes(self):
        """A profile configuration is requested of the LXD client."""
        ctx = context.get_admin_context()
        instance = fake_instance.fake_instance_obj(
            ctx, name='test', memory_mb=0)
        instance.flavor.extra_specs = {
            'quota:disk_read_bytes_sec': '3000000',
            'quota:disk_write_bytes_sec': '4000000',
        }
        network_info = []
        block_info = []

        expected_config = {
            'environment.product_name': 'OpenStack Nova',
            'limits.cpu': '1',
            'limits.memory': '0MB',
            'raw.lxc': (
                'lxc.console.logfile=/var/log/lxd/{}/console.log\n'.format(
                    instance.name)),
        }
        expected_devices = {
            'root': {
                'limits.read': '2MB',
                'limits.write': '3MB',
                'path': '/',
                'size': '0GB',
                'type': 'disk'
            },
        }

        flavor.to_profile(self.client, instance, network_info, block_info)

        self.client.profiles.create.assert_called_once_with(
            instance.name, expected_config, expected_devices)

    def test_to_profile_quota_extra_specs_iops(self):
        """A profile configuration is requested of the LXD client."""
        ctx = context.get_admin_context()
        instance = fake_instance.fake_instance_obj(
            ctx, name='test', memory_mb=0)
        instance.flavor.extra_specs = {
            'quota:disk_read_iops_sec': '300',
            'quota:disk_write_iops_sec': '400',
        }
        network_info = []
        block_info = []

        expected_config = {
            'environment.product_name': 'OpenStack Nova',
            'limits.cpu': '1',
            'limits.memory': '0MB',
            'raw.lxc': (
                'lxc.console.logfile=/var/log/lxd/{}/console.log\n'.format(
                    instance.name)),
        }
        expected_devices = {
            'root': {
                'limits.read': '300iops',
                'limits.write': '400iops',
                'path': '/',
                'size': '0GB',
                'type': 'disk'
            },
        }

        flavor.to_profile(self.client, instance, network_info, block_info)

        self.client.profiles.create.assert_called_once_with(
            instance.name, expected_config, expected_devices)

    def test_to_profile_quota_extra_specs_max_bytes(self):
        """A profile configuration is requested of the LXD client."""
        ctx = context.get_admin_context()
        instance = fake_instance.fake_instance_obj(
            ctx, name='test', memory_mb=0)
        instance.flavor.extra_specs = {
            'quota:disk_total_bytes_sec': '6000000',
        }
        network_info = []
        block_info = []

        expected_config = {
            'environment.product_name': 'OpenStack Nova',
            'limits.cpu': '1',
            'limits.memory': '0MB',
            'raw.lxc': (
                'lxc.console.logfile=/var/log/lxd/{}/console.log\n'.format(
                    instance.name)),
        }
        expected_devices = {
            'root': {
                'limits.max': '5MB',
                'path': '/',
                'size': '0GB',
                'type': 'disk'
            },
        }

        flavor.to_profile(self.client, instance, network_info, block_info)

        self.client.profiles.create.assert_called_once_with(
            instance.name, expected_config, expected_devices)

    def test_to_profile_quota_extra_specs_max_iops(self):
        """A profile configuration is requested of the LXD client."""
        ctx = context.get_admin_context()
        instance = fake_instance.fake_instance_obj(
            ctx, name='test', memory_mb=0)
        instance.flavor.extra_specs = {
            'quota:disk_total_iops_sec': '500',
        }
        network_info = []
        block_info = []

        expected_config = {
            'environment.product_name': 'OpenStack Nova',
            'limits.cpu': '1',
            'limits.memory': '0MB',
            'raw.lxc': (
                'lxc.console.logfile=/var/log/lxd/{}/console.log\n'.format(
                    instance.name)),
        }
        expected_devices = {
            'root': {
                'limits.max': '500iops',
                'path': '/',
                'size': '0GB',
                'type': 'disk'
            },
        }

        flavor.to_profile(self.client, instance, network_info, block_info)

        self.client.profiles.create.assert_called_once_with(
            instance.name, expected_config, expected_devices)

    @mock.patch('nova.virt.lxd.vif._is_no_op_firewall', return_value=False)
    def test_to_profile_network_config_average(self, _is_no_op_firewall):
        ctx = context.get_admin_context()
        instance = fake_instance.fake_instance_obj(
            ctx, name='test', memory_mb=0)
        instance.flavor.extra_specs = {
            'quota:vif_inbound_average': '1000000',
            'quota:vif_outbound_average': '2000000',
        }
        network_info = [{
            'id': '0123456789abcdef',
            'type': network_model.VIF_TYPE_OVS,
            'address': '00:11:22:33:44:55',
            'network': {
                'bridge': 'fakebr'},
            'devname': 'tap0123456789a'}]
        block_info = []

        expected_config = {
            'environment.product_name': 'OpenStack Nova',
            'limits.cpu': '1',
            'limits.memory': '0MB',
            'raw.lxc': (
                'lxc.console.logfile=/var/log/lxd/{}/console.log\n'.format(
                    instance.name)),
        }
        expected_devices = {
            'tap0123456789a': {
                'hwaddr': '00:11:22:33:44:55',
                'nictype': 'physical',
                'parent': 'tin0123456789a',
                'type': 'nic',
                'limits.egress': '16000Mbit',
                'limits.ingress': '8000Mbit',
            },
            'root': {
                'path': '/',
                'size': '0GB',
                'type': 'disk'
            },
        }

        flavor.to_profile(self.client, instance, network_info, block_info)

        self.client.profiles.create.assert_called_once_with(
            instance.name, expected_config, expected_devices)

    @mock.patch('nova.virt.lxd.vif._is_no_op_firewall', return_value=False)
    def test_to_profile_network_config_peak(self, _is_no_op_firewall):
        ctx = context.get_admin_context()
        instance = fake_instance.fake_instance_obj(
            ctx, name='test', memory_mb=0)
        instance.flavor.extra_specs = {
            'quota:vif_inbound_peak': '3000000',
            'quota:vif_outbound_peak': '4000000',
        }
        network_info = [{
            'id': '0123456789abcdef',
            'type': network_model.VIF_TYPE_OVS,
            'address': '00:11:22:33:44:55',
            'network': {
                'bridge': 'fakebr'},
            'devname': 'tap0123456789a'}]
        block_info = []

        expected_config = {
            'environment.product_name': 'OpenStack Nova',
            'limits.cpu': '1',
            'limits.memory': '0MB',
            'raw.lxc': (
                'lxc.console.logfile=/var/log/lxd/{}/console.log\n'.format(
                    instance.name)),
        }
        expected_devices = {
            'tap0123456789a': {
                'hwaddr': '00:11:22:33:44:55',
                'nictype': 'physical',
                'parent': 'tin0123456789a',
                'type': 'nic',
                'limits.egress': '32000Mbit',
                'limits.ingress': '24000Mbit',
            },
            'root': {
                'path': '/',
                'size': '0GB',
                'type': 'disk'
            },
        }

        flavor.to_profile(self.client, instance, network_info, block_info)

        self.client.profiles.create.assert_called_once_with(
            instance.name, expected_config, expected_devices)

    @mock.patch('nova.virt.lxd.flavor.driver.block_device_info_get_ephemerals')
    def test_to_profile_ephemeral_storage(self, get_ephemerals):
        """A profile configuration is requested of the LXD client."""
        get_ephemerals.return_value = [
            {'virtual_name': 'ephemeral1'},
        ]

        ctx = context.get_admin_context()
        instance = fake_instance.fake_instance_obj(
            ctx, name='test', memory_mb=0)
        network_info = []
        block_info = []

        expected_config = {
            'environment.product_name': 'OpenStack Nova',
            'limits.cpu': '1',
            'limits.memory': '0MB',
            'raw.lxc': (
                'lxc.console.logfile=/var/log/lxd/{}/console.log\n'.format(
                    instance.name)),
        }
        expected_devices = {
            'root': {
                'path': '/',
                'size': '0GB',
                'type': 'disk'
            },
            'ephemeral1': {
                'type': 'disk',
                'path': '/mnt',
                'source': '/i/{}/storage/ephemeral1'.format(instance.name),
            },
        }

        flavor.to_profile(self.client, instance, network_info, block_info)

        self.client.profiles.create.assert_called_once_with(
            instance.name, expected_config, expected_devices)
