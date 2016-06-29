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

import fixtures
import mock
import os

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

        self.tempdir = self.useFixture(fixtures.TempDir()).path
        self.flags(instances_path=self.tempdir)

    def test_create_storage(self):
        """Verify the correct calls are made."""
        self.volumeops.create_storage(
            mock.sentinel.block_device_info,
            mock.sentinel.instance)
        self.volumeops.storage_driver. \
            create_storage.assert_called_once_with(
                mock.sentinel.block_device_info,
                mock.sentinel.instance)

    def test_remove_storage(self):
        """Verify the correct calls are made."""
        self.volumeops.remove_storage(
            mock.sentinel.block_device_info,
            mock.sentinel.instance
        )
        self.volumeops.storage_driver. \
            remove_storage.assert_called_once_with(
                mock.sentinel.block_device_info,
                mock.sentinel.instance
            )

    @mock.patch('nova.virt.lxd.volumeops.ensure_ephemeral')
    def test_is_ephemeral_valid(self, mock_ensure_empeheral):
        """"Verify that ephemeral block device check is correct."""
        instance = mock.Mock()
        block_device_info = mock.Mock()
        mock_ensure_empeheral.return_value = {'name': 'fake_ephemreal'}
        self.assertTrue(self.volumeops.is_ephemeral(
            block_device_info, instance))

    @mock.patch('nova.virt.lxd.volumeops.ensure_ephemeral')
    def test_is_ephemeral_invalid(self, mock_ensure_ephemeral):
        """"Verify that ephemeral block device check is incorrect."""
        instance = mock.Mock()
        block_device_info = mock.Mock()
        mock_ensure_ephemeral.return_value = {}
        self.assertFalse(self.volumeops.is_ephemeral(
            block_device_info, instance))

    @mock.patch('os.path.join')
    def test_ensure_empeheral(self, fake_path):
        """Verify the disk mappings is correct for a given instance
           block device.
        """
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

    @mock.patch.object(session.LXDAPISession, 'get_host_config',
                       mock.Mock(return_value={'storage': 'zfs'}))
    def test_disk_mapping_with_ephemeral_flavor(self):
        """Ensure block device is translated correctly
           when flavor.ephemeral_root_gb is set.
        """
        instance = stubs._fake_instance()
        block_device_info = {}
        mapping = self.volumeops.get_disk_mapping(instance, block_device_info)
        self.assertEqual({'path': '/',
                          'size': '10GB',
                          'type': 'disk'}, mapping['root'])
        self.assertEqual({
            'type': 'disk',
            'path': '/mnt',
            'source': os.path.join(
                    self.tempdir, instance.name,
                    'storage', 'instance-00000001-ephemeral')},
            mapping['instance-00000001-ephemeral'])

    @mock.patch.object(session.LXDAPISession, 'get_host_config',
                       mock.Mock(return_value={'storage': 'zfs'}))
    def test_disk_mapping_root_with_zfs(self):
        """Ensure root disk configuration is translated correctly
           when zfs is set.
        """
        instance = stubs._fake_instance()
        block_device_info = {}
        instance.flavor.ephemeral_gb = 0
        mapping = self.volumeops.get_disk_mapping(instance, block_device_info)
        self.assertEqual({'path': '/',
                          'size': '10GB',
                          'type': 'disk'}, mapping['root'])

    @mock.patch.object(session.LXDAPISession, 'get_host_config',
                       mock.Mock(return_value={'storage': 'zfs'}))
    def test_disk_mapping_root_with_zfs_and_empheral(self):
        """Ensure root disk configuration and empeheral is translated correctly
           when zfs is set.
        """
        instance = stubs._fake_instance()
        block_device_info = {'swap': None,
                             'ephemerals': [
                                 {'size': 1,
                                  'virtual_name': 'ephemeral0',
                                  'num': 0,
                                  'device_name': u'/dev/sdb'}],
                             'block_device_mapping': [],
                             'root_device_name': u'/dev/sda'}
        instance.flavor.ephemeral_gb = 0
        mapping = self.volumeops.get_disk_mapping(instance, block_device_info)
        self.assertEqual({'path': '/',
                          'size': '10GB',
                          'type': 'disk'}, mapping['root'])
        self.assertEqual({'path': '/mnt',
                          'source': os.path.join(
                              self.tempdir, instance.name, 'storage',
                              'ephemeral0'),
                          'type': 'disk'}, mapping['ephemeral0'])

    @mock.patch.object(session.LXDAPISession, 'get_host_config',
                       mock.Mock(return_value={'storage': 'lvm'}))
    def test_disk_mapping_with_lvm_ephemeral_flavor(self):
        """Ensure root disk configuration and empeheral is translated correctly
           when lvm is set.
        """
        instance = stubs._fake_instance()
        block_device_info = {}
        mapping = self.volumeops.get_disk_mapping(instance, block_device_info)
        self.assertEqual({'path': '/',
                          'size': '10GB',
                          'type': 'disk'}, mapping['root'])
        self.assertEqual({'type': 'disk',
                          'path': '/mnt',
                          'source': os.path.join(
                              self.tempdir, instance.name, 'storage',
                              'instance-00000001-ephemeral')},
                         mapping['instance-00000001-ephemeral'])

    @mock.patch.object(session.LXDAPISession, 'get_host_config',
                       mock.Mock(return_value={'storage': 'lvm'}))
    def test_disk_mapping_root_with_lvm(self):
        """Ensure root disk configuration is translated correctly
           when lvm is set.
        """
        instance = stubs._fake_instance()
        block_device_info = {}
        instance.flavor.ephemeral_gb = 0
        mapping = self.volumeops.get_disk_mapping(instance, block_device_info)
        self.assertEqual({'path': '/',
                          'size': '10GB',
                          'type': 'disk'}, mapping['root'])
