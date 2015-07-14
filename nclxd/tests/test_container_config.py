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
from oslo_config import cfg

from nclxd.nova.virt.lxd import container_config
from nclxd import tests

CONF = cfg.CONF


@ddt.ddt
class LXDTestContainerConfig(test.NoDBTestCase):

    def setUp(self):
        super(LXDTestContainerConfig, self).setUp()
        self.container_config = container_config.LXDContainerConfig()

    def test_init_config(self):
        self.assertEqual({'config': {}, 'devices': {}},
                         self.container_config._init_container_config())

    @mock.patch.object(CONF, 'lxd', lxd_default_profile='fake_profile')
    @mock.patch('nclxd.nova.virt.lxd.container_image'
                '.LXDContainerImage.fetch_image')
    @mock.patch('nclxd.nova.virt.lxd.container_utils'
                '.LXDContainerDirectories.get_console_path',
                return_value='/fake/path')
    @tests.annotated_data(
        ('no_rescue', {}, 'mock_instance'),
        ('rescue', {'name_label': 'rescued', 'rescue': True}, 'rescued'),
    )
    def test_configure_container(self, tag, kwargs, expected, mp, mf, mc):
        instance = tests.MockInstance()
        context = {}
        network_info = []
        image_meta = {}
        self.assertEqual(
            {'config': {'raw.lxc':
                        'lxc.console.logfile=/fake/path\n'},
             'devices': {},
             'name': expected,
             'profiles': ['fake_profile'],
             'source': {'alias': 'None', 'type': 'image'}},
            (self.container_config
             .configure_container(context,
                                  instance,
                                  network_info,
                                  image_meta,
                                  **kwargs)))
        mf.assert_called_once_with(context, instance, image_meta)
        mp.assert_called_once_with('mock_instance')

    @mock.patch('nclxd.nova.virt.lxd.container_utils'
                '.LXDContainerDirectories.get_console_path',
                return_value='/fake/path')
    @tests.annotated_data(
        ('no_limits', {'memory_mb': -1, 'vcpus': 0},
         {}),
        ('mem_limit', {'memory_mb': 2048, 'vcpus': 0},
         {'limits.memory': '2147483648'}),
        ('cpu_limit', {'memory_mb': -1, 'vcpus': 10},
         {'limits.cpus': '10'}),
        ('both_limits', {'memory_mb': 4096, 'vcpus': 20},
         {'limits.memory': '4294967296', 'limits.cpus': '20'}),
    )
    def test_configure_container_config(self, tag, flavor, expected, mp):
        instance = tests.MockInstance(**flavor)
        config = {'raw.lxc': 'lxc.console.logfile=/fake/path\n'}
        config.update(expected)
        self.assertEqual(
            {'config': config},
            self.container_config.configure_container_config({},
                                                             instance))
        mp.assert_called_once_with('mock_instance')

    def test_configure_network_devices(self):
        instance = tests.MockInstance()
        network_info = (
            {
                'id': '0123456789abcdef',
                'address': '00:11:22:33:44:55',
            },
            {
                'id': 'fedcba9876543210',
                'address': '66:77:88:99:aa:bb',
            })

        self.assertEqual({
            'devices': {
                'qbr0123456789a': {
                    'nictype': 'bridged',
                    'hwaddr': '00:11:22:33:44:55',
                    'parent': 'qbr0123456789a',
                    'type': 'nic'
                },
                'qbrfedcba98765': {
                    'nictype': 'bridged',
                    'hwaddr': '66:77:88:99:aa:bb',
                    'parent': 'qbrfedcba98765',
                    'type': 'nic'
                }}},
            self.container_config.configure_network_devices(
                {}, instance, network_info))

    @mock.patch('nclxd.nova.virt.lxd.container_utils'
                '.LXDContainerDirectories.get_container_rootfs',
                return_value='/fake/path')
    def test_configure_container_rescuedisk(self, mp):
        instance = tests.MockInstance()
        self.assertEqual({
            'devices':
            {'rescue': {'path': 'mnt',
                        'source': '/fake/path',
                        'type': 'disk'}}},
            self.container_config.configure_container_rescuedisk(
                {}, instance))
        mp.assert_called_once_with('mock_instance')

    @mock.patch.object(CONF, 'config_drive_format', new='fake-format')
    def test_configure_container_configdrive_wrong_format(self):
        instance = tests.MockInstance()
        self.assertRaises(
            exception.InstancePowerOnFailure,
            self.container_config.configure_container_configdrive,
            {}, instance, {}, 'secret')

    @mock.patch.object(CONF, 'config_drive_format', new=None)
    @mock.patch('nova.api.metadata.base.InstanceMetadata')
    @mock.patch('nclxd.nova.virt.lxd.container_utils'
                '.LXDContainerDirectories.get_container_configdrive',
                side_effect=exception.NovaException)
    def test_configure_container_configdrive_fail(self, md, mi):
        instance = tests.MockInstance()
        injected_files = mock.Mock()
        self.assertRaises(
            exception.NovaException,
            self.container_config.configure_container_configdrive,
            {}, instance, injected_files, 'secret')
        md.assert_called_once_with('mock_instance')
        mi.assert_called_once_with(
            instance, content=injected_files, extra_md={})

    @mock.patch.object(CONF, 'config_drive_format', new=None)
    @mock.patch('nova.api.metadata.base.InstanceMetadata')
    @mock.patch('nova.virt.configdrive.ConfigDriveBuilder')
    @mock.patch('nclxd.nova.virt.lxd.container_utils'
                '.LXDContainerDirectories.get_container_configdrive',
                return_value='/fake/path')
    def test_configure_container_configdrive_fail_dir(self, mp, md, mi):
        instance = tests.MockInstance()
        injected_files = mock.Mock()
        with mock.patch.object(self.container_config, 'configure_disk_path',
                               side_effect=exception.NovaException) as mdir:
            self.assertRaises(
                exception.NovaException,
                self.container_config.configure_container_configdrive,
                {}, instance, injected_files, 'secret')
            mdir.assert_called_once_with({}, 'configdrive', instance)
        mp.assert_called_once_with('mock_instance')
        md.assert_called_once_with(instance_md=mi.return_value)
        (md.return_value.__enter__.return_value
         .make_drive.assert_called_once_with('/fake/path'))
        mi.assert_called_once_with(
            instance, content=injected_files, extra_md={})

    @mock.patch.object(CONF, 'config_drive_format', new=None)
    @mock.patch('nova.api.metadata.base.InstanceMetadata')
    @mock.patch('nova.virt.configdrive.ConfigDriveBuilder')
    @mock.patch('nclxd.nova.virt.lxd.container_utils'
                '.LXDContainerDirectories.get_container_configdrive',
                return_value='/fake/path')
    def test_configure_container_configdrive(self, mp, md, mi):
        instance = tests.MockInstance()
        injected_files = mock.Mock()
        self.assertEqual(
            {'devices': {'configdrive': {'path': 'mnt',
                                         'type': 'disk',
                                         'source': '/fake/path'}}},
            self.container_config.configure_container_configdrive(
                {}, instance, injected_files, 'secret'))
        self.assertEqual([mock.call('mock_instance')] * 2, mp.call_args_list)
        md.assert_called_once_with(instance_md=mi.return_value)
        (md.return_value.__enter__.return_value
         .make_drive.assert_called_once_with('/fake/path'))
        mi.assert_called_once_with(
            instance, content=injected_files, extra_md={})
