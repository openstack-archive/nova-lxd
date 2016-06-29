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

