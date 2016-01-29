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

from nova import exception
from nova import test
from nova.tests.unit import fake_network

from nova_lxd.nova.virt.lxd import config
from nova_lxd.nova.virt.lxd import utils as container_dir
from nova_lxd.tests import stubs


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
        config = self.config._create_config(instance_name, instance)
        self.assertEqual(config[key], expected)

    def test_create_network(self):
        instance = stubs._fake_instance()
        instance_name = 'fake_instance'
        network_info = fake_network.fake_get_instance_nw_info(self)
        config = self.config._create_network(instance_name, instance,
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
                                        'type': 'disk'}}, config)

    @mock.patch('os.path.exists', mock.Mock(return_value=False))
    def test_create_disk_path_fail(self):
        instance = stubs._fake_instance()
        self.assertRaises(exception.NovaException,
                          self.config.configure_disk_path, 'fake_source',
                          'fake_dir', 'fake_type', instance)

    def test_create_container_source(self):
        instance = stubs._fake_instance()
        config = self.config._get_container_source(instance)
        self.assertEqual(config, {'type': 'image', 'alias': 'fake_image'})
