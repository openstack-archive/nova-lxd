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

from nova import test
import stubs

from nova.virt.lxd import session
from nova.virt.lxd import volumeops


class LXDTestContainerVolume(test.NoDBTestCase):
    """LXD Container volume unit tests."""

    def setUp(self):

        super(LXDTestContainerVolume, self).setUp()

        self.volumeops = volumeops.LXDVolumeOps()
        self.volumeops.storage_driver = mock.MagicMock()

    def test_create_storage(self):
        self.volumeops.create_storage(
            mock.sentinel.block_device_info,
            mock.sentinel.instance)
        self.volumeops.storage_driver.create_storage.assert_called_once_with(
            mock.sentinel.block_device_info,
            mock.sentinel.instance)

    def test_remove_storage(self):
        self.volumeops.remove_storage(
            mock.sentinel.block_device_info,
            mock.sentinel.instance
        )
        self.volumeops.storage_driver.remove_storage.assert_called_once_with(
            mock.sentinel.block_device_info,
            mock.sentinel.instance
        )

    @mock.patch('nova.virt.lxd.volumeops.ensure_ephemeral')
    def test_is_ephemeral_valid(self, mock_ensure_empeheral):
        instance = mock.Mock()
        block_device_info = mock.Mock()
        mock_ensure_empeheral.return_value = {'name': 'fake_ephemreal'}
        self.assertTrue(self.volumeops.is_ephemeral(
            block_device_info, instance))

    @mock.patch('nova.virt.lxd.volumeops.ensure_ephemeral')
    def test_is_ephemeral_invalid(self, mock_ensure_ephemeral):
        instance = mock.Mock()
        block_device_info = mock.Mock()
        mock_ensure_ephemeral.return_value = {}
        self.assertFalse(self.volumeops.is_ephemeral(
            block_device_info, instance))

    @mock.patch('os.path.join')
    def test_ensure_empeheral(self, fake_path):
        instance = mock.Mock()
        block_device_info = {'swap': None,
                             'ephemerals': [
                                 {'size': 1,
                                  'virtual_name': 'ephemeral0',
                                  'num': 0,
                                  'device_name': u'/dev/sdb'}],
                             'block_device_mapping': [],
                             'root_device_name': u'/dev/sda'}
        fake_path.return_value = '/fake/fake_image/storage/fake'
        ephemeral_config = volumeops.ensure_ephemeral(
            block_device_info, instance)
        self.assertEqual('ephemeral0', ephemeral_config['name'])
        self.assertEqual(1, ephemeral_config['size'])
        self.assertEqual('/fake/fake_image/storage/fake',
                         ephemeral_config['src_dir'])
        self.assertEqual('/mnt', ephemeral_config['dest_dir'])

    @mock.patch('os.path.join')
    def test_ensure_empeheral(self, fake_path):
        instance = stubs._fake_instance()
        block_device_info = {}
        fake_path.return_value = '/fake/fake_image/storage/fake'
        ephemeral_config = volumeops.ensure_ephemeral(
            block_device_info, instance)
        self.assertEqual('instance-00000001-ephemeral',
                         ephemeral_config['name'])
        self.assertEqual(1, ephemeral_config['size'])
        self.assertEqual('/fake/fake_image/storage/fake',
                         ephemeral_config['src_dir'])
        self.assertEqual('/mnt', ephemeral_config['dest_dir'])

    def test_get_disk_mapping(self):
        instance = stubs._fake_instance()
        block_device_info = {}
        self.lxd_config = {'storage': 'zfs'}
        mapping = self.volumeops.get_disk_mapping(instance, block_device_info)
