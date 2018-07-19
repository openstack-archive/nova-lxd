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

from nova.virt.lxd import storage


class TestAttachEphemeral(test.NoDBTestCase):
    """Tests for nova.virt.lxd.storage.attach_ephemeral."""

    def setUp(self):
        super(TestAttachEphemeral, self).setUp()

        self.patchers = []

        CONF_patcher = mock.patch('nova.virt.lxd.common.conf.CONF')
        self.patchers.append(CONF_patcher)
        self.CONF = CONF_patcher.start()
        self.CONF.instances_path = '/i'
        self.CONF.lxd.root_dir = '/var/lib/lxd'

    def tearDown(self):
        super(TestAttachEphemeral, self).tearDown()
        for patcher in self.patchers:
            patcher.stop()

    @mock.patch.object(storage.utils, 'execute')
    @mock.patch(
        'nova.virt.lxd.storage.driver.block_device_info_get_ephemerals')
    def test_add_ephemerals_with_zfs(
            self, block_device_info_get_ephemerals, execute):
        ctx = context.get_admin_context()
        block_device_info_get_ephemerals.return_value = [
            {'virtual_name': 'ephemerals0'}]
        instance = fake_instance.fake_instance_obj(
            ctx, name='test', memory_mb=0)
        block_device_info = mock.Mock()
        lxd_config = {'environment': {'storage': 'zfs'},
                      'config': {'storage.zfs_pool_name': 'zfs'}}

        container = mock.Mock()
        container.config = {
            'volatile.last_state.idmap': '[{"Isuid":true,"Isgid":false,'
            '"Hostid":165536,"Nsid":0,'
            '"Maprange":65536}]'
        }
        client = mock.Mock()
        client.containers.get.return_value = container

        storage.attach_ephemeral(
            client, block_device_info, lxd_config, instance)

        block_device_info_get_ephemerals.assert_called_once_with(
            block_device_info)

        expected_calls = [
            mock.call(
                'zfs', 'create', '-o',
                'mountpoint=/i/instance-00000001/storage/ephemerals0', '-o',
                'quota=0G', 'zfs/instance-00000001-ephemeral',
                run_as_root=True),
            mock.call(
                'chown', '165536', '/i/instance-00000001/storage/ephemerals0',
                run_as_root=True)
        ]

        self.assertEqual(expected_calls, execute.call_args_list)

    @mock.patch.object(storage.utils, 'execute')
    @mock.patch(
        'nova.virt.lxd.storage.driver.block_device_info_get_ephemerals')
    def test_add_ephemerals_with_btrfs(
            self, block_device_info_get_ephemerals, execute):
        ctx = context.get_admin_context()
        block_device_info_get_ephemerals.return_value = [
            {'virtual_name': 'ephemerals0'}]
        instance = fake_instance.fake_instance_obj(
            ctx, name='test', memory_mb=0)
        instance.ephemeral_gb = 1
        block_device_info = mock.Mock()
        lxd_config = {'environment': {'storage': 'btrfs'}}
        profile = mock.Mock()
        profile.devices = {
            'root': {
                'path': '/',
                'type': 'disk',
                'size': '1G'
            },
            'ephemerals0': {
                'optional': 'True',
                'path': '/mnt',
                'source': '/path/fake_path',
                'type': 'disk'

            }
        }
        client = mock.Mock()
        client.profiles.get.return_value = profile

        container = mock.Mock()
        container.config = {
            'volatile.last_state.idmap': '[{"Isuid":true,"Isgid":false,'
            '"Hostid":165536,"Nsid":0,'
            '"Maprange":65536}]'
        }
        client.containers.get.return_value = container

        storage.attach_ephemeral(
            client, block_device_info, lxd_config, instance)

        block_device_info_get_ephemerals.assert_called_once_with(
            block_device_info)
        profile.save.assert_called_once_with()

        expected_calls = [
            mock.call(
                'btrfs', 'subvolume', 'create',
                '/var/lib/lxd/containers/instance-00000001/ephemerals0',
                run_as_root=True),
            mock.call(
                'btrfs', 'qgroup', 'limit', '1g',
                '/var/lib/lxd/containers/instance-00000001/ephemerals0',
                run_as_root=True),
            mock.call(
                'chown', '165536',
                '/var/lib/lxd/containers/instance-00000001/ephemerals0',
                run_as_root=True)
        ]
        self.assertEqual(expected_calls, execute.call_args_list)
        self.assertEqual(
            profile.devices['ephemerals0']['source'],
            '/var/lib/lxd/containers/instance-00000001/ephemerals0')

    @mock.patch.object(storage.utils, 'execute')
    @mock.patch(
        'nova.virt.lxd.storage.driver.block_device_info_get_ephemerals')
    def test_ephemeral_with_lvm(
            self, block_device_info_get_ephemerals, execute):
        ctx = context.get_admin_context()
        block_device_info_get_ephemerals.return_value = [
            {'virtual_name': 'ephemerals0'}]
        instance = fake_instance.fake_instance_obj(
            ctx, name='test', memory_mb=0)
        block_device_info = mock.Mock()
        lxd_config = {'environment': {'storage': 'lvm'},
                      'config': {'storage.lvm_vg_name': 'lxd'}}

        storage.fileutils = mock.Mock()

        container = mock.Mock()
        container.config = {
            'volatile.last_state.idmap': '[{"Isuid":true,"Isgid":false,'
            '"Hostid":165536,"Nsid":0,'
            '"Maprange":65536}]'
        }
        client = mock.Mock()
        client.containers.get.return_value = container

        storage.attach_ephemeral(
            client, block_device_info, lxd_config, instance)

        block_device_info_get_ephemerals.assert_called_once_with(
            block_device_info)

        expected_calls = [
            mock.call(
                'lvcreate', '-L', '0G', '-n', 'instance-00000001-ephemerals0',
                'lxd', attempts=3, run_as_root=True),
            mock.call(
                'mkfs', '-t', 'ext4', '/dev/lxd/instance-00000001-ephemerals0',
                run_as_root=True),
            mock.call(
                'mount', '-t', 'ext4',
                '/dev/lxd/instance-00000001-ephemerals0',
                '/i/instance-00000001/storage/ephemerals0',
                run_as_root=True),
            mock.call(
                'chown', '165536', '/i/instance-00000001/storage/ephemerals0',
                run_as_root=True)]
        self.assertEqual(expected_calls, execute.call_args_list)


class TestDetachEphemeral(test.NoDBTestCase):
    """Tests for nova.virt.lxd.storage.detach_ephemeral."""

    @mock.patch.object(storage.utils, 'execute')
    @mock.patch(
        'nova.virt.lxd.storage.driver.block_device_info_get_ephemerals')
    def test_remove_ephemeral_with_zfs(
            self, block_device_info_get_ephemerals, execute):
        block_device_info_get_ephemerals.return_value = [
            {'virtual_name': 'ephemerals0'}]

        ctx = context.get_admin_context()
        instance = fake_instance.fake_instance_obj(
            ctx, name='test', memory_mb=0)
        block_device_info = mock.Mock()
        lxd_config = {'environment': {'storage': 'zfs'},
                      'config': {'storage.zfs_pool_name': 'zfs'}}

        client = mock.Mock()
        storage.detach_ephemeral(
            client, block_device_info, lxd_config, instance)

        block_device_info_get_ephemerals.assert_called_once_with(
            block_device_info)

        expected_calls = [
            mock.call('zfs', 'destroy', 'zfs/instance-00000001-ephemeral',
                      run_as_root=True)
        ]
        self.assertEqual(expected_calls, execute.call_args_list)

    @mock.patch.object(storage.utils, 'execute')
    @mock.patch(
        'nova.virt.lxd.storage.driver.block_device_info_get_ephemerals')
    def test_remove_ephemeral_with_lvm(
            self, block_device_info_get_ephemerals, execute):
        block_device_info_get_ephemerals.return_value = [
            {'virtual_name': 'ephemerals0'}]

        ctx = context.get_admin_context()
        instance = fake_instance.fake_instance_obj(
            ctx, name='test', memory_mb=0)
        block_device_info = mock.Mock()
        lxd_config = {'environment': {'storage': 'lvm'},
                      'config': {'storage.lvm_vg_name': 'lxd'}}

        client = mock.Mock()
        storage.detach_ephemeral(
            client, block_device_info, lxd_config, instance)

        block_device_info_get_ephemerals.assert_called_once_with(
            block_device_info)

        expected_calls = [
            mock.call(
                'umount', '/dev/lxd/instance-00000001-ephemerals0',
                run_as_root=True),
            mock.call('lvremove', '-f',
                      '/dev/lxd/instance-00000001-ephemerals0',
                      run_as_root=True)
        ]
        self.assertEqual(expected_calls, execute.call_args_list)
