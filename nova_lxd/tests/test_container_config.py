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

from nova_lxd.nova.virt.lxd import container_config
from nova_lxd.nova.virt.lxd import utils as container_dir
from nova_lxd.tests import stubs


@ddt.ddt
@mock.patch.object(container_config, 'CONF', stubs.MockConf())
@mock.patch.object(container_dir, 'CONF', stubs.MockConf())
class LXDTestContainerConfig(test.NoDBTestCase):

    def setUp(self):
        super(LXDTestContainerConfig, self).setUp()
        self.container_config = container_config.LXDContainerConfig()

    def test_init_config(self):
        self.assertEqual({'config': {}, 'devices': {}},
                         self.container_config._init_container_config())

    @stubs.annotated_data(
        ('mem_limit', {'memory_mb': 2048},
         {'limits.memory': '2147483648'}),
        ('both_limits', {'memory_mb': 4096},
         {'limits.memory': '4294967296'}),
    )
    @mock.patch('oslo_utils.fileutils.ensure_tree',
                mock.Mock(return_value=None))
    @mock.patch('os.mkdir',
                mock.Mock(return_value=None))
    def test_configure_container_config(self, tag, flavor, expected):
        instance = stubs.MockInstance(**flavor)
        config = {'raw.lxc': 'lxc.console.logfile=/fake/lxd/root/containers/'
                             'fake-uuid/console.log\n'}
        config.update(expected)
        self.assertEqual(
            {'config': config},
            self.container_config.configure_container_config({},
                                                             instance))

    def test_configure_network_devices(self):
        instance = stubs._fake_instance()
        self.assertEqual(None,
                         self.container_config.configure_network_devices(
                             {}, instance, network_info=[]))

    def test_configure_container_rescuedisk(self):
        instance = stubs.MockInstance()
        self.assertEqual({
            'devices':
            {'rescue': {'path': 'mnt',
                        'source': '/fake/lxd/root/containers/'
                                  'fake-uuid-backup/rootfs',
                        'type': 'disk'}}},
            self.container_config.configure_container_rescuedisk(
                {}, instance))

    def test_configure_container_configdrive_wrong_format(self):
        instance = stubs.MockInstance()
        with mock.patch.object(container_config.CONF, 'config_drive_format',
                               new='fake-format'):
            self.assertRaises(
                exception.InstancePowerOnFailure,
                self.container_config.configure_container_configdrive,
                {}, instance, {})

    @mock.patch('nova.api.metadata.base.InstanceMetadata')
    def test_configure_container_configdrive_fail(self, mi):
        instance = None
        injected_files = mock.Mock()
        self.assertRaises(
            AttributeError,
            self.container_config.configure_container_configdrive,
            {}, instance, injected_files)
        mi.assert_called_once_with(
            instance, content=injected_files, extra_md={})

    @mock.patch('nova.api.metadata.base.InstanceMetadata')
    @mock.patch('nova.virt.configdrive.ConfigDriveBuilder')
    def test_configure_container_configdrive_fail_dir(self, md, mi):
        instance = stubs.MockInstance()
        injected_files = mock.Mock()
        self.assertRaises(
            AttributeError,
            self.container_config.configure_container_configdrive,
            None, instance, injected_files)
        md.assert_called_once_with(instance_md=mi.return_value)
        (md.return_value.__enter__.return_value
         .make_drive.assert_called_once_with(
             '/fake/instances/path/fake-uuid/config-drive'))
        mi.assert_called_once_with(
            instance, content=injected_files, extra_md={})

    @mock.patch('nova.api.metadata.base.InstanceMetadata')
    @mock.patch('nova.virt.configdrive.ConfigDriveBuilder')
    def test_configure_container_configdrive(self, md, mi):
        instance = stubs.MockInstance()
        injected_files = mock.Mock()
        self.assertEqual(
            {'devices': {'configdrive':
                         {'path': 'mnt',
                          'type': 'disk',
                          'source': '/fake/instances/path/'
                                    'fake-uuid/config-drive'}}},
            self.container_config.configure_container_configdrive(
                {}, instance, injected_files))
        md.assert_called_once_with(instance_md=mi.return_value)
        (md.return_value.__enter__.return_value
         .make_drive.assert_called_once_with(
             '/fake/instances/path/fake-uuid/config-drive'))
        mi.assert_called_once_with(
            instance, content=injected_files, extra_md={})
