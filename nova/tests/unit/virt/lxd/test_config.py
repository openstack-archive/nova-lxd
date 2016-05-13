# Copyright 2015 Canonical Ltd
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

import ddt
import mock

from nova import test
from nova.tests.unit import fake_network

from nova.virt.lxd import config
from nova.virt.lxd import session
from nova.virt.lxd import utils as container_dir
from oslo_utils import units

import stubs


@ddt.ddt
@mock.patch.object(config, 'CONF', stubs.MockConf())
@mock.patch.object(container_dir, 'CONF', stubs.MockConf())
class LXDTestContainerConfig(test.NoDBTestCase):
    """LXD Container configuration unit tests."""

    def setUp(self):
        super(LXDTestContainerConfig, self).setUp()
        self.config = config.LXDContainerConfig()

    @stubs.annotated_data(
        ('test_name', 'name', 'instance-00000001'),
        ('test_source', 'source', {'type': 'image',
                                   'alias': 'fake_image'}),
        ('test_devices', 'devices', {})
    )
    def test_create_container(self, tag, key, expected):
        """Tests the create_container methond on LXDContainerConfig.
           Inspect that the correct dictionary is returned for a given
           instance.
        """
        instance = stubs._fake_instance()
        container_config = self.config.create_container(instance)
        self.assertEqual(container_config[key], expected)

    @stubs.annotated_data(
        ('test_memmoy', 'limits.memory', '512MB')
    )
    def test_create_config(self, tag, key, expected):
        instance = stubs._fake_instance()
        instance_name = 'fake_instance'
        config = self.config.create_config(instance_name, instance)
        self.assertEqual(config[key], expected)

    def test_create_network(self):
        instance = stubs._fake_instance()
        instance_name = 'fake_instance'
        network_info = fake_network.fake_get_instance_nw_info(self)
        config = self.config.create_network(instance_name, instance,
                                            network_info)
        self.assertEqual({'fake_br1': {'hwaddr': 'DE:AD:BE:EF:00:01',
                                       'nictype': 'bridged',
                                       'parent': 'fake_br1',
                                       'type': 'nic'}}, config)

    @mock.patch('os.path.exists', mock.Mock(return_value=True))
    def test_create_disk_path(self):
        instance = stubs._fake_instance()
        config = self.config.configure_disk_path('/fake/src_path',
                                                 '/fake/dest_path',
                                                 'fake_disk', instance)
        self.assertEqual({'fake_disk': {'path': '/fake/dest_path',
                                        'source': '/fake/src_path',
                                        'type': 'disk',
                                        'optional': 'True'}}, config)

    def test_config_instance_options(self):
        instance = stubs._fake_instance()
        config = {}
        container_config = self.config.config_instance_options(config,
                                                               instance)
        self.assertEqual({'boot.autostart': 'True'}, container_config)

    def test_create_container_source(self):
        instance = stubs._fake_instance()
        config = self.config.get_container_source(instance)
        self.assertEqual(config, {'type': 'image', 'alias': 'fake_image'})

    @mock.patch.object(session.LXDAPISession, 'get_host_config',
                       mock.Mock(return_value={'storage': 'btrfs'}))
    def test_container_root_btrfs(self):
        instance = stubs._fake_instance()
        config = self.config.configure_container_root(instance)
        self.assertEqual({'root': {'path': '/',
                                   'type': 'disk',
                                   'size': '10GB'}}, config)

    @mock.patch.object(session.LXDAPISession, 'get_host_config',
                       mock.Mock(return_value={'storage': 'zfs'}))
    def test_container_root_zfs(self):
        instance = stubs._fake_instance()
        config = self.config.configure_container_root(instance)
        self.assertEqual({'root': {'path': '/',
                                   'type': 'disk',
                                   'size': '10GB'}}, config)

    @mock.patch.object(session.LXDAPISession, 'get_host_config',
                       mock.Mock(return_value={'storage': 'lvm'}))
    def test_container_root_lvm(self):
        instance = stubs._fake_instance()
        config = self.config.configure_container_root(instance)
        self.assertEqual({'root': {'path': '/',
                                   'type': 'disk'}}, config)

    def test_container_nested_container(self):
        instance = stubs._fake_instance()
        instance.flavor.extra_specs = {'lxd:nested_allowed': True}
        config = self.config.config_instance_options({}, instance)
        self.assertEqual({'security.nesting': 'True',
                          'boot.autostart': 'True'}, config)

    def test_container_privileged_container(self):
        instance = stubs._fake_instance()
        instance.flavor.extra_specs = {'lxd:privileged_allowed': True}
        config = self.config.config_instance_options({}, instance)
        self.assertEqual({'security.privileged': 'True',
                          'boot.autostart': 'True'}, config)

    @mock.patch.object(session.LXDAPISession, 'get_host_config',
                       mock.Mock(return_value={'storage': 'zfs'}))
    def test_disk_quota_rw_iops(self):
        instance = stubs._fake_instance()
        instance.flavor.extra_specs = {'quota:disk_read_iops_sec': 10000,
                                       'quota:disk_write_iops_sec': 10000}
        config = self.config.configure_container_root(instance)
        self.assertEqual({'root': {'path': '/',
                                   'type': 'disk',
                                   'size': '10GB',
                                   'limits.read': '10000iops',
                                   'limits.write': '10000iops'}}, config)

    @mock.patch.object(session.LXDAPISession, 'get_host_config',
                       mock.Mock(return_value={'storage': 'zfs'}))
    def test_disk_quota_rw_iops_and_bytes(self):
        # Byte values should take precedence
        instance = stubs._fake_instance()
        instance.flavor.extra_specs = {
            'quota:disk_read_iops_sec': 10000,
            'quota:disk_write_iops_sec': 10000,
            'quota:disk_read_bytes_sec': 13 * units.Mi,
            'quota:disk_write_bytes_sec': 5 * units.Mi
        }
        config = self.config.configure_container_root(instance)
        self.assertEqual({'root': {'path': '/',
                                   'type': 'disk',
                                   'size': '10GB',
                                   'limits.read': '13MB',
                                   'limits.write': '5MB'}}, config)

    @mock.patch.object(session.LXDAPISession, 'get_host_config',
                       mock.Mock(return_value={'storage': 'zfs'}))
    def test_disk_quota_total_iops(self):
        instance = stubs._fake_instance()
        instance.flavor.extra_specs = {
            'quota:disk_total_iops_sec': 10000
        }
        config = self.config.configure_container_root(instance)
        self.assertEqual({'root': {'path': '/',
                                   'type': 'disk',
                                   'size': '10GB',
                                   'limits.max': '10000iops'}}, config)

    @mock.patch.object(session.LXDAPISession, 'get_host_config',
                       mock.Mock(return_value={'storage': 'zfs'}))
    def test_disk_quota_total_iops_and_bytes(self):
        instance = stubs._fake_instance()
        instance.flavor.extra_specs = {
            'quota:disk_total_iops_sec': 10000,
            'quota:disk_total_bytes_sec': 11 * units.Mi
        }
        config = self.config.configure_container_root(instance)
        self.assertEqual({'root': {'path': '/',
                                   'type': 'disk',
                                   'size': '10GB',
                                   'limits.max': '11MB'}}, config)

    @mock.patch.object(session.LXDAPISession, 'get_host_config',
                       mock.Mock(return_value={'storage': 'zfs'}))
    def test_disk_quota_rw_and_total_iops_and_bytes(self):
        # More granular quotas should be set only, moreover
        # in MBytes, not iops
        instance = stubs._fake_instance()
        instance.flavor.extra_specs = {
            'quota:disk_read_iops_sec': 10000,
            'quota:disk_write_iops_sec': 10000,
            'quota:disk_read_bytes_sec': 13 * units.Mi,
            'quota:disk_write_bytes_sec': 5 * units.Mi,
            'quota:disk_total_iops_sec': 10000,
            'quota:disk_total_bytes_sec': 11 * units.Mi
        }
        config = self.config.configure_container_root(instance)
        self.assertEqual({'root': {'path': '/',
                                   'type': 'disk',
                                   'size': '10GB',
                                   'limits.read': '13MB',
                                   'limits.write': '5MB'}}, config)

    def test_network_in_out_average(self):
        instance = stubs._fake_instance()
        instance.flavor.extra_specs = {
            'quota:vif_inbound_average': 20 * units.M,
            'quota:vif_outbound_average': 8 * units.M
        }
        instance_name = 'fake_instance'
        network_info = fake_network.fake_get_instance_nw_info(self)
        config = self.config.create_network(instance_name, instance,
                                            network_info)
        self.assertEqual({'fake_br1': {'hwaddr': 'DE:AD:BE:EF:00:01',
                                       'nictype': 'bridged',
                                       'parent': 'fake_br1',
                                       'type': 'nic',
                                       'limits.ingress': '20Mbit',
                                       'limits.egress': '8Mbit'}}, config)

    def test_network_in_out_average_and_peak(self):
        # Max of the two values should take precedence
        instance = stubs._fake_instance()
        instance.flavor.extra_specs = {
            'quota:vif_inbound_average': 20 * units.M,
            'quota:vif_outbound_average': 9 * units.M,
            'quota:vif_inbound_peak': 21 * units.M,
            'quota:vif_outbound_peak': 8 * units.M,
        }
        instance_name = 'fake_instance'
        network_info = fake_network.fake_get_instance_nw_info(self)
        config = self.config.create_network(instance_name, instance,
                                            network_info)
        self.assertEqual({'fake_br1': {'hwaddr': 'DE:AD:BE:EF:00:01',
                                       'nictype': 'bridged',
                                       'parent': 'fake_br1',
                                       'type': 'nic',
                                       'limits.ingress': '21Mbit',
                                       'limits.egress': '9Mbit'}}, config)
