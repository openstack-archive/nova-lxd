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

from nova import exception
from nova import test

from nova.virt.lxd import volumeops
from nova.virt.lxd.storage import fs


class LXDTestStorageFS(test.NoDBTestCase):
    """LXD Container storage unit tests."""

    @mock.patch('oslo_utils.fileutils.ensure_tree')
    @mock.patch('nova.utils.execute')
    @mock.patch('os.path.exists')
    def test_create_storage(
            self, mock_ensure_tree, mock_execute, mock_os_path):
        """Verify the correct calls were made."""
        instance = mock.Mock()
        block_device_info = mock.Mock()
        mock_os_path.return_value = True

        with mock.patch.object(volumeops, 'ensure_ephemeral',
                               return_value={'src_dir': '/fake/path'}):
            fs_driver = fs.LXDFSStorageDriver()
            fs_driver.create_storage(block_device_info, instance)

            expected_call = [
                mock.call(
                    'chown', '-R', '166536:166536',
                    '/fake/path', run_as_root=True)]

            self.assertEqual(expected_call, mock_execute.call_args_list)

    @mock.patch('os.path.exists')
    @mock.patch('shutil.rmtree')
    @mock.patch('nova.utils.execute')
    def test_remove_storage(self, mock_os_exists, mock_rmtree, mock_execute):
        """Verify the correct calls were made."""
        instance = mock.Mock()
        block_device_info = mock.Mock()
        mock_os_exists.return_value = True

        with mock.patch.object(volumeops, 'ensure_ephemeral',
                               return_value={'src_dir': '/fake/path'}):
            fs_driver = fs.LXDFSStorageDriver()
            fs_driver.remove_storage(block_device_info, instance)
            mock_rmtree.assert_called_once_with('/fake/path')

    def test_fs_resize(self):
        """Verifty resize raises an exception."""
        instance = mock.Mock()
        block_device_info = mock.Mock()

        fs_driver = fs.LXDFSStorageDriver()
        self.assertRaises(exception.CannotResizeDisk,
                          fs_driver.resize_storage,
                          block_device_info, instance)
