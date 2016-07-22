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
import collections

import mock
from nova import context
from nova import exception
from nova import test
from nova.compute import power_state
from nova.network import model as network_model
from nova.tests.unit import fake_instance
from pylxd import exceptions as lxdcore_exceptions
import six

from nova.virt.lxd import driver
from nova.virt.lxd import utils

MockResponse = collections.namedtuple('Response', ['status_code'])

MockContainer = collections.namedtuple('Container', ['name'])
MockContainerState = collections.namedtuple(
    'ContainerState', ['status_code', 'memory'])


def fake_connection_info(volume, location, iqn, auth=False, transport=None):
    dev_name = 'ip-%s-iscsi-%s-lun-1' % (location, iqn)
    if transport is not None:
        dev_name = 'pci-0000:00:00.0-' + dev_name
    dev_path = '/dev/disk/by-path/%s' % (dev_name)
    ret = {
        'driver_volume_type': 'iscsi',
        'data': {
            'volume_id': volume['id'],
            'target_portal': location,
            'target_iqn': iqn,
            'target_lun': 1,
            'device_path': dev_path,
            'qos_specs': {
                'total_bytes_sec': '102400',
                'read_iops_sec': '200',
            }
        }
    }
    if auth:
        ret['data']['auth_method'] = 'CHAP'
        ret['data']['auth_username'] = 'foo'
        ret['data']['auth_password'] = 'bar'
    return ret


class LXDDriverTest(test.NoDBTestCase):
    """Tests for nova.virt.lxd.driver.LXDDriver."""

    def setUp(self):
        super(LXDDriverTest, self).setUp()

        self.Client_patcher = mock.patch('nova.virt.lxd.driver.pylxd.Client')
        self.Client = self.Client_patcher.start()

        self.client = mock.Mock()
        self.Client.return_value = self.client

        self.CONF_patcher = mock.patch('nova.virt.lxd.driver.CONF')
        self.CONF = self.CONF_patcher.start()
        self.CONF.instances_path = '/path/to/instances'
        self.CONF.my_ip = '0.0.0.0'

    def tearDown(self):
        super(LXDDriverTest, self).tearDown()
        self.Client_patcher.stop()
        self.CONF_patcher.stop()

    def test_init_host(self):
        """init_host initializes the pylxd Client."""
        lxd_driver = driver.LXDDriver(None)
        lxd_driver.init_host(None)

        self.Client.assert_called_once_with()
        self.assertEqual(self.client, lxd_driver.client)

    def test_init_host_fail(self):
        def side_effect():
            raise lxdcore_exceptions.ClientConnectionFailed()
        self.Client.side_effect = side_effect
        self.Client.return_value = None

        lxd_driver = driver.LXDDriver(None)

        self.assertRaises(exception.HostNotFound, lxd_driver.init_host, None)

    def test_get_info(self):
        container = mock.Mock()
        container.state.return_value = MockContainerState(
            100, {'usage': 4000, 'usage_peak': 4500})
        self.client.containers.get.return_value = container

        ctx = context.get_admin_context()
        instance = fake_instance.fake_instance_obj(ctx, name='test')
        lxd_driver = driver.LXDDriver(None)
        lxd_driver.init_host(None)

        info = lxd_driver.get_info(instance)

        self.assertEqual(power_state.RUNNING, info.state)
        self.assertEqual(3, info.mem_kb)
        self.assertEqual(4, info.max_mem_kb)
        self.assertEqual(1, info.num_cpu)
        self.assertEqual(0, info.cpu_time_ns)

    def test_list_instances(self):
        self.client.containers.all.return_value = [
            MockContainer('mock-instance-1'),
            MockContainer('mock-instance-2'),
        ]
        lxd_driver = driver.LXDDriver(None)
        lxd_driver.init_host(None)

        instances = lxd_driver.list_instances()

        self.assertEqual(['mock-instance-1', 'mock-instance-2'], instances)

    def test_spawn(self):
        def container_get(*args, **kwargs):
            raise lxdcore_exceptions.LXDAPIException(MockResponse(404))
        self.client.containers.get.side_effect = container_get

        ctx = context.get_admin_context()
        instance = fake_instance.fake_instance_obj(ctx, name='test')
        image_meta = mock.Mock()
        injected_files = mock.Mock()
        admin_password = mock.Mock()
        network_info = [mock.Mock()]
        block_device_info = mock.Mock()

        # NOTE: mock out fileutils to ensure that unit tests don't try
        #       to manipulate the filesystem (breaks in package builds).
        driver.fileutils = mock.Mock()

        lxd_driver = driver.LXDDriver(None)
        lxd_driver.init_host(None)
        # XXX: rockstar (6 Jul 2016) - There are a number of XXX comments
        # related to these calls in spawn. They require some work before we
        # can take out these mocks and follow the real codepaths.
        lxd_driver.setup_image = mock.Mock()
        lxd_driver.vif_driver = mock.Mock()
        lxd_driver.firewall_driver = mock.Mock()
        lxd_driver._add_ephemeral = mock.Mock()
        lxd_driver.create_profile = mock.Mock(return_value={
            'name': instance.name, 'config': {}, 'devices': {}})

        lxd_driver.spawn(
            ctx, instance, image_meta, injected_files, admin_password,
            network_info, block_device_info)

        lxd_driver.setup_image.assert_called_once_with(
            ctx, instance, image_meta)
        lxd_driver.vif_driver.plug.assert_called_once_with(
            instance, network_info[0])
        lxd_driver.create_profile.assert_called_once_with(
            instance, network_info, block_device_info)
        fd = lxd_driver.firewall_driver
        fd.setup_basic_filtering.assert_called_once_with(
            instance, network_info)
        fd.prepare_instance_filter.assert_called_once_with(
            instance, network_info)
        fd.apply_instance_filter.assert_called_once_with(
            instance, network_info)
        lxd_driver._add_ephemeral.assert_called_once_with(
            block_device_info, lxd_driver.client.host_info, instance)

    def test_spawn_already_exists(self):
        """InstanceExists is raised if the container already exists."""
        ctx = context.get_admin_context()
        instance = fake_instance.fake_instance_obj(ctx, name='test')
        image_meta = mock.Mock()
        injected_files = mock.Mock()
        admin_password = mock.Mock()

        lxd_driver = driver.LXDDriver(None)
        lxd_driver.init_host(None)

        self.assertRaises(
            exception.InstanceExists,

            lxd_driver.spawn,
            ctx, instance, image_meta, injected_files, admin_password,
            None, None)

    @mock.patch('nova.virt.lxd.driver.container_utils.get_container_storage')
    @mock.patch.object(driver.utils, 'execute')
    @mock.patch('nova.virt.driver.block_device_info_get_ephemerals')
    def test_add_ephemerals_with_zfs(
            self, block_device_info_get_ephemerals, execute,
            get_container_storage):
        ctx = context.get_admin_context()
        block_device_info_get_ephemerals.return_value = [
            {'virtual_name': 'ephemerals0'}]
        instance = fake_instance.fake_instance_obj(ctx, name='test')
        block_device_info = mock.Mock()
        lxd_config = {'environment': {'storage': 'zfs'},
                      'config': {'storage.zfs_pool_name': 'zfs'}}
        get_container_storage.return_value = '/path'

        container = mock.Mock()
        container.config = {
            'volatile.last_state.idmap': '[{"Isuid":true,"Isgid":false,'
            '"Hostid":165536,"Nsid":0,'
            '"Maprange":65536}]'
        }
        self.client.containers.get.return_value = container

        lxd_driver = driver.LXDDriver(None)
        lxd_driver.init_host(None)
        lxd_driver._add_ephemeral(block_device_info, lxd_config, instance)

        block_device_info_get_ephemerals.assert_called_once_with(
            block_device_info)

        expected_calls = [
            mock.call(
                'zfs', 'create', '-o', 'mountpoint=/path', '-o', 'quota=0G',
                'zfs/instance-00000001-ephemeral', run_as_root=True),
            mock.call('chown', '165536', '/path', run_as_root=True)
        ]

        self.assertEqual(expected_calls, execute.call_args_list)

    @mock.patch('nova.virt.lxd.driver.container_utils.get_container_dir')
    @mock.patch.object(driver.utils, 'execute')
    @mock.patch('nova.virt.driver.block_device_info_get_ephemerals')
    def test_add_ephemerals_with_btrfs(
            self, block_device_info_get_ephemerals, execute,
            get_container_dir):
        ctx = context.get_admin_context()
        block_device_info_get_ephemerals.return_value = [
            {'virtual_name': 'ephemerals0'}]
        instance = fake_instance.fake_instance_obj(ctx, name='test')
        instance.ephemeral_gb = 1
        block_device_info = mock.Mock()
        lxd_config = {'environment': {'storage': 'btrfs'}}
        get_container_dir.return_value = '/path'
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
        self.client.profiles.get.return_value = profile

        container = mock.Mock()
        container.config = {
            'volatile.last_state.idmap': '[{"Isuid":true,"Isgid":false,'
            '"Hostid":165536,"Nsid":0,'
            '"Maprange":65536}]'
        }
        self.client.containers.get.return_value = container

        lxd_driver = driver.LXDDriver(None)
        lxd_driver.init_host(None)
        lxd_driver._add_ephemeral(block_device_info, lxd_config, instance)

        block_device_info_get_ephemerals.assert_called_once_with(
            block_device_info)
        profile.save.assert_called_once_with()

        expected_calls = [
            mock.call(
                'btrfs', 'subvolume', 'create',
                '/path/instance-00000001/ephemerals0',
                run_as_root=True),
            mock.call(
                'btrfs', 'qgroup', 'limit', '1g',
                '/path/instance-00000001/ephemerals0', run_as_root=True),
            mock.call(
                'chown', '165536', '/path/instance-00000001/ephemerals0',
                run_as_root=True)
        ]
        self.assertEqual(expected_calls, execute.call_args_list)
        self.assertEqual(profile.devices['ephemerals0']['source'],
                         '/path/instance-00000001/ephemerals0')

    @mock.patch('nova.virt.lxd.driver.container_utils.get_container_storage')
    @mock.patch.object(driver.utils, 'execute')
    @mock.patch('nova.virt.driver.block_device_info_get_ephemerals')
    def test_ephemeral_with_lvm(
            self, block_device_info_get_ephemerals, execute,
            get_container_storage):
        ctx = context.get_admin_context()
        block_device_info_get_ephemerals.return_value = [
            {'virtual_name': 'ephemerals0'}]
        instance = fake_instance.fake_instance_obj(ctx, name='test')
        block_device_info = mock.Mock()
        lxd_config = {'environment': {'storage': 'lvm'},
                      'config': {'storage.lvm_vg_name': 'lxd'}}
        get_container_storage.return_value = '/path'

        driver.fileutils = mock.Mock()

        container = mock.Mock()
        container.config = {
            'volatile.last_state.idmap': '[{"Isuid":true,"Isgid":false,'
            '"Hostid":165536,"Nsid":0,'
            '"Maprange":65536}]'
        }
        self.client.containers.get.return_value = container

        lxd_driver = driver.LXDDriver(None)
        lxd_driver.init_host(None)
        lxd_driver._add_ephemeral(block_device_info, lxd_config, instance)

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
                '/dev/lxd/instance-00000001-ephemerals0', '/path',
                run_as_root=True),
            mock.call(
                'chown', '165536', '/path', run_as_root=True)]
        self.assertEqual(expected_calls, execute.call_args_list)

    def test_destroy(self):
        mock_profile = mock.Mock()
        mock_container = mock.Mock()
        mock_container.status = 'Running'
        self.client.profiles.get.return_value = mock_profile
        self.client.containers.get.return_value = mock_container
        ctx = context.get_admin_context()
        instance = fake_instance.fake_instance_obj(ctx, name='test')
        network_info = [mock.Mock()]

        lxd_driver = driver.LXDDriver(None)
        lxd_driver.init_host(None)
        lxd_driver.cleanup = mock.Mock()  # There is a separate cleanup test

        lxd_driver.destroy(ctx, instance, network_info)

        lxd_driver.cleanup.assert_called_once_with(
            ctx, instance, network_info, None)
        lxd_driver.client.profiles.get.assert_called_once_with(instance.name)
        mock_profile.delete.assert_called_once_with()
        lxd_driver.client.containers.get.assert_called_once_with(instance.name)
        mock_container.stop.assert_called_once_with(wait=True)
        mock_container.delete.assert_called_once_with(wait=True)

    @mock.patch('os.path.exists', mock.Mock(return_value=True))
    @mock.patch('pwd.getpwuid')
    @mock.patch('shutil.rmtree')
    @mock.patch.object(driver.utils, 'execute')
    def test_cleanup(self, execute, rmtree, getpwuid):
        pwuid = mock.Mock()
        pwuid.pw_name = 'user'
        getpwuid.return_value = pwuid

        ctx = context.get_admin_context()
        instance = fake_instance.fake_instance_obj(ctx, name='test')
        network_info = [mock.Mock()]
        instance_dir = utils.get_instance_dir(instance.name)
        block_device_info = mock.Mock()

        lxd_driver = driver.LXDDriver(None)
        lxd_driver.init_host(None)
        lxd_driver.vif_driver = mock.Mock()
        lxd_driver.firewall_driver = mock.Mock()
        lxd_driver._remove_ephemeral = mock.Mock()

        lxd_driver.cleanup(ctx, instance, network_info, block_device_info)

        lxd_driver.vif_driver.unplug.assert_called_once_with(
            instance, network_info[0])
        lxd_driver.firewall_driver.unfilter_instance.assert_called_once_with(
            instance, network_info)
        lxd_driver._remove_ephemeral.assert_called_once_with(
            block_device_info, lxd_driver.client.host_info, instance)
        execute.assert_called_once_with(
            'chown', '-R', 'user:user', instance_dir, run_as_root=True)
        rmtree.assert_called_once_with(instance_dir)

    @mock.patch.object(driver.utils, 'execute')
    @mock.patch('nova.virt.driver.block_device_info_get_ephemerals')
    def test_remove_emepheral_with_zfs(
            self, block_device_info_get_ephemerals, execute):
        block_device_info_get_ephemerals.return_value = [
            {'virtual_name': 'ephemerals0'}]

        ctx = context.get_admin_context()
        instance = fake_instance.fake_instance_obj(ctx, name='test')
        block_device_info = mock.Mock()
        lxd_config = {'environment': {'storage': 'zfs'},
                      'config': {'storage.zfs_pool_name': 'zfs'}}

        lxd_driver = driver.LXDDriver(None)
        lxd_driver.init_host(None)
        lxd_driver._remove_ephemeral(block_device_info, lxd_config, instance)

        block_device_info_get_ephemerals.assert_called_once_with(
            block_device_info)

        expected_calls = [
            mock.call('zfs', 'destroy', 'zfs/instance-00000001-ephemeral',
                      run_as_root=True)
        ]
        self.assertEqual(expected_calls, execute.call_args_list)

    @mock.patch.object(driver.utils, 'execute')
    @mock.patch('nova.virt.driver.block_device_info_get_ephemerals')
    def test_remove_emepheral_with_lvm(
            self, block_device_info_get_ephemerals, execute):
        block_device_info_get_ephemerals.return_value = [
            {'virtual_name': 'ephemerals0'}]

        ctx = context.get_admin_context()
        instance = fake_instance.fake_instance_obj(ctx, name='test')
        block_device_info = mock.Mock()
        lxd_config = {'environment': {'storage': 'lvm'},
                      'config': {'storage.lvm_vg_name': 'lxd'}}

        lxd_driver = driver.LXDDriver(None)
        lxd_driver.init_host(None)
        lxd_driver._remove_ephemeral(block_device_info, lxd_config, instance)

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

    def test_reboot(self):
        ctx = context.get_admin_context()
        instance = fake_instance.fake_instance_obj(ctx, name='test')

        lxd_driver = driver.LXDDriver(None)
        lxd_driver.init_host(None)

        lxd_driver.reboot(ctx, instance, None, None)

        self.client.containers.get.assert_called_once_with(instance.name)

    @mock.patch('pwd.getpwuid', mock.Mock(return_value=mock.Mock(pw_uid=1234)))
    @mock.patch('os.getuid', mock.Mock())
    @mock.patch('os.path.exists', mock.Mock(return_value=True))
    @mock.patch('six.moves.builtins.open')
    @mock.patch.object(driver.utils, 'execute')
    def test_get_console_output(self, execute, _open):
        ctx = context.get_admin_context()
        instance = fake_instance.fake_instance_obj(ctx, name='test')
        expected_calls = [
            mock.call(
                'chown', '1234:1234', '/var/log/lxd/{}/console.log'.format(
                    instance.name),
                run_as_root=True),
            mock.call(
                'chmod', '755', '/var/lib/lxd/containers/{}'.format(
                    instance.name),
                run_as_root=True),
        ]
        _open.return_value.__enter__.return_value = six.BytesIO(b'output')

        lxd_driver = driver.LXDDriver(None)

        contents = lxd_driver.get_console_output(context, instance)

        self.assertEqual(b'output', contents)
        self.assertEqual(expected_calls, execute.call_args_list)

    def test_get_host_ip_addr(self):
        lxd_driver = driver.LXDDriver(None)

        result = lxd_driver.get_host_ip_addr()

        self.assertEqual('0.0.0.0', result)

    def test_attach_interface(self):
        expected = {
            'hwaddr': '00:11:22:33:44:55',
            'parent': 'qbr0123456789a',
            'nictype': 'bridged',
            'type': 'nic',
        }

        container = mock.Mock()
        container.expanded_devices = {
            'eth0': {
                'name': 'eth0',
                'nictype': 'bridged',
                'parent': 'lxdbr0',
                'type': 'nic'
            },
            'root': {
                'path': '/',
                'type': 'disk'
            },
        }
        self.client.containers.get.return_value = container

        ctx = context.get_admin_context()
        instance = fake_instance.fake_instance_obj(ctx, name='test')
        image_meta = None
        vif = {
            'id': '0123456789abcdef',
            'type': network_model.VIF_TYPE_OVS,
            'address': '00:11:22:33:44:55',
            'network': {
                'bridge': 'fakebr'}}

        lxd_driver = driver.LXDDriver(None)
        lxd_driver.init_host(None)
        lxd_driver.vif_driver = mock.Mock()
        lxd_driver.vif_driver.get_config.return_value = {
            'mac_address': '00:11:22:33:44:55', 'bridge': 'qbr0123456789a',
        }
        lxd_driver.firewall_driver = mock.Mock()

        lxd_driver.attach_interface(instance, image_meta, vif)

        self.assertTrue('eth1' in container.expanded_devices)
        self.assertEqual(expected, container.expanded_devices['eth1'])
        container.save.assert_called_once_with(wait=True)

    def test_detach_interface(self):
        container = mock.Mock()
        container.expanded_devices = {
            'eth0': {
                'name': 'eth0',
                'nictype': 'bridged',
                'parent': 'lxdbr0',
                'hwaddr': '00:11:22:33:44:55',
                'type': 'nic'
            },
            'root': {
                'path': '/',
                'type': 'disk'
            },
        }
        self.client.containers.get.return_value = container

        ctx = context.get_admin_context()
        instance = fake_instance.fake_instance_obj(ctx, name='test')
        vif = {
            'id': '0123456789abcdef',
            'type': network_model.VIF_TYPE_OVS,
            'address': '00:11:22:33:44:55',
            'network': {
                'bridge': 'fakebr'}}

        lxd_driver = driver.LXDDriver(None)
        lxd_driver.init_host(None)
        lxd_driver.vif_driver = mock.Mock()

        lxd_driver.detach_interface(instance, vif)

        lxd_driver.vif_driver.unplug.assert_called_once_with(
            instance, vif)
        self.assertEqual(['root'], sorted(container.expanded_devices.keys()))
        container.save.assert_called_once_with(wait=True)

    def test_migrate_disk_and_power_off(self):
        container = mock.Mock()
        self.client.containers.get.return_value = container
        profile = mock.Mock()
        self.client.profiles.get.return_value = profile

        ctx = context.get_admin_context()
        instance = fake_instance.fake_instance_obj(ctx, name='test')
        dest = '0.0.0.0'
        flavor = mock.Mock()
        network_info = []

        lxd_driver = driver.LXDDriver(None)
        lxd_driver.init_host(None)
        # XXX: rockstar (12 Jul 2016) - This is a weird fault line for the
        # legacy code and the new updated logic. I *suspect* this is probably
        # okay until we remove create_profile entirely (see its XXX comment).
        lxd_driver.create_profile = mock.Mock(return_value={
            'name': instance.name, 'config': {}, 'devices': {}})

        lxd_driver.migrate_disk_and_power_off(
            ctx, instance, dest, flavor, network_info)

        profile.save.assert_called_once_with()
        container.stop.assert_called_once_with(wait=True)

    def test_migrate_disk_and_power_off_different_host(self):
        """Migrating to a different host only shuts down the container."""
        container = mock.Mock()
        self.client.containers.get.return_value = container

        ctx = context.get_admin_context()
        instance = fake_instance.fake_instance_obj(ctx, name='test')
        dest = '0.0.0.1'
        flavor = mock.Mock()
        network_info = []

        lxd_driver = driver.LXDDriver(None)
        lxd_driver.init_host(None)

        lxd_driver.migrate_disk_and_power_off(
            ctx, instance, dest, flavor, network_info)

        self.assertEqual(0, self.client.profiles.get.call_count)
        container.stop.assert_called_once_with(wait=True)

    @mock.patch('os.readlink')
    def test_attach_volume(self, readlink):
        profile = mock.Mock()
        self.client.profiles.get.return_value = profile
        readlink.return_value = '/dev/sdc'
        ctx = context.get_admin_context()
        instance = fake_instance.fake_instance_obj(ctx, name='test')
        connection_info = fake_connection_info(
            {'id': 1, 'name': 'volume-00000001'},
            '10.0.2.15:3260', 'iqn.2010-10.org.openstack:volume-00000001',
            auth=True)
        mountpoint = mock.Mock()

        lxd_driver = driver.LXDDriver(None)
        lxd_driver.init_host(None)

        lxd_driver.storage_driver.connect_volume = mock.MagicMock()
        lxd_driver.attach_volume(
            ctx, connection_info, instance, mountpoint, None, None, None)

        lxd_driver.client.profiles.get.assert_called_once_with(instance.name)
        lxd_driver.storage_driver.connect_volume.assert_called_once_with(
            connection_info['data'])
        profile.save.assert_called_once_with()

    def test_detach_volume(self):
        profile = mock.Mock()
        profile.devices = {
            'eth0': {
                'name': 'eth0',
                'nictype': 'bridged',
                'parent': 'lxdbr0',
                'type': 'nic'
            },
            'root': {
                'path': '/',
                'type': 'disk'
            },
            1: {
                'path': '/dev/sdc',
                'type': 'unix-block'
            },
        }

        expected = {
            'eth0': {
                'name': 'eth0',
                'nictype': 'bridged',
                'parent': 'lxdbr0',
                'type': 'nic'
            },
            'root': {
                'path': '/',
                'type': 'disk'
            },
        }

        self.client.profiles.get.return_value = profile
        ctx = context.get_admin_context()
        instance = fake_instance.fake_instance_obj(ctx, name='test')
        connection_info = fake_connection_info(
            {'id': 1, 'name': 'volume-00000001'},
            '10.0.2.15:3260', 'iqn.2010-10.org.openstack:volume-00000001',
            auth=True)
        mountpoint = mock.Mock()

        lxd_driver = driver.LXDDriver(None)
        lxd_driver.init_host(None)

        lxd_driver.storage_driver.disconnect_volume = mock.MagicMock()
        lxd_driver.detach_volume(connection_info, instance, mountpoint, None)

        lxd_driver.client.profiles.get.assert_called_once_with(instance.name)

        self.assertEqual(expected, profile.devices)
        profile.save.assert_called_once_with()

    def test_pause(self):
        container = mock.Mock()
        self.client.containers.get.return_value = container
        ctx = context.get_admin_context()
        instance = fake_instance.fake_instance_obj(ctx, name='test')

        lxd_driver = driver.LXDDriver(None)
        lxd_driver.init_host(None)

        lxd_driver.pause(instance)

        self.client.containers.get.assert_called_once_with(instance.name)
        container.freeze.assert_called_once_with(instance.name, wait=True)

    def test_unpause(self):
        container = mock.Mock()
        self.client.containers.get.return_value = container
        ctx = context.get_admin_context()
        instance = fake_instance.fake_instance_obj(ctx, name='test')

        lxd_driver = driver.LXDDriver(None)
        lxd_driver.init_host(None)

        lxd_driver.unpause(instance)

        self.client.containers.get.assert_called_once_with(instance.name)
        container.unfreeze.assert_called_once_with(instance.name, wait=True)

    def test_suspend(self):
        container = mock.Mock()
        self.client.containers.get.return_value = container
        ctx = context.get_admin_context()
        instance = fake_instance.fake_instance_obj(ctx, name='test')

        lxd_driver = driver.LXDDriver(None)
        lxd_driver.init_host(None)

        lxd_driver.suspend(ctx, instance)

        self.client.containers.get.assert_called_once_with(instance.name)
        container.freeze.assert_called_once_with(instance.name, wait=True)

    def test_resume(self):
        container = mock.Mock()
        self.client.containers.get.return_value = container
        ctx = context.get_admin_context()
        instance = fake_instance.fake_instance_obj(ctx, name='test')

        lxd_driver = driver.LXDDriver(None)
        lxd_driver.init_host(None)

        lxd_driver.resume(ctx, instance, None, None)

        self.client.containers.get.assert_called_once_with(instance.name)
        container.unfreeze.assert_called_once_with(instance.name, wait=True)
