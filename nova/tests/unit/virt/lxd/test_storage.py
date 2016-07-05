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

from nova.virt.lxd import storage


class LXDTestStorage(test.NoDBTestCase):

    def setUp(self):
        super(LXDTestStorage, self).setUp()

        self.storage = storage.LXDStorageDriver('fs')

    def test_get_volume_driver_fs(self):
        """Verify the correct class is called."""
        result = self.storage.get_storage_driver()
        result = isinstance(result, storage.LXDFSStorage)
        self.assertTrue(result)

    def test_create_storage(self):
        instance = stubs._fake_instance()
        block_device_info = mock.Mock()
        self.assertEqual(None,
                         self.storage.create_storage(
                             block_device_info, instance))

    def test_remove_storage(self):
        instance = stubs._fake_instance()
        block_device_info = mock.Mock()
        self.assertEqual(None,
                         self.storage.remove_storage(
                             block_device_info, instance))
