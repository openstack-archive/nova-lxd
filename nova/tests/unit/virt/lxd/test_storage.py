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
from nova import utils
from nova.tests.unit import fake_instance

from nova.virt.lxd.storage import zfs


class LXDDStorageTest(test.NoDBTestCase):
    """Tests for nova.virt.storage."""
    def setUp(self):
        super(LXDDStorageTest, self).setUp()


    @mock.patch('nova.virt.lxd.utils.get_container_storage')
    @mock.patch('nova.virt.lxd.utils.get_container_rootfs')
    @mock.patch('os.stat')
    def test_zfs_create_storage(self, mock_container_storage, mock_container_rootfs,
        mock_os_stat):

        class FakeStatResult(object):
            def __init__(self):
                self.f_bsize = 4096
                self.f_frsize = 4096
                self.f_blocks = 2000
                self.f_bfree = 1000
                self.f_bavail = 900
                self.f_files = 2000
                self.f_ffree = 1000
                self.f_favail = 900
                self.f_flag = 4096
                self.f_namemax = 255

        self.path = None

        def fake_stat(path):
            self.path = path
            return FakeStatResult()

        ctxt = context.get_admin_context()
        instance = fake_instance.fake_instance_obj(ctxt, name='test')
        instance.ephemeral_gb = 1
        storage = {'virtual_name': 'ephemeral0'}
        lxd_config = {'config': {'storage.zfs_pool_name': 'zfs'}}

        mock_container_rootfs.return_value = '/fake/rootfs'
        mock_container_storage.return_value = '/fake/storage'
        mock_os_stat.return_value = fake_stat('/fake/rootfs')

        executes = []

        def fake_execute(*args, **kwargs):
            executes.append(args)
            return "", ""

        self.stubs.Set(utils, 'execute', fake_execute)

        zfs.create_storage(storage, instance, lxd_config)
        expected = []
        self.assertEqual(expected, executes)
