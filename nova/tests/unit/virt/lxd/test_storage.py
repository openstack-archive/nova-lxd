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
from nova import test
from nova.tests.unit import fake_instance

from nova.virt.lxd.storage import zfs


class LXDDStorageTest(test.NoDBTestCase):
    """Tests for nova.virt.storage."""

    def setUp(self):
        super(LXDDStorageTest, self).setUp()

    @mock.patch('nova.virt.lxd.utils.get_container_rootfs')
    @mock.patch('nova.virt.lxd.utils.get_container_storage')
    @mock.patch('nova.utils.execute')
    @mock.patch('os.stat')
    def test_zfs_create_storage(
            self, mock_os_stat, mock_execute, mock_container_storage,
            mock_container_rootfs):
        ctxt = context.get_admin_context()
        instance = fake_instance.fake_instance_obj(ctxt, name='test')
        instance.ephemeral_gb = 1
        storage = {'virtual_name': 'ephemeral0'}
        lxd_config = {'config': {'storage.zfs_pool_name': 'zfs'}}

        mock_os_stat.return_value.st_uid = 1234

        self.assertEqual(None,
                         zfs.create_storage(storage, instance, lxd_config))
