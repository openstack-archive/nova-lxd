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
from nova.tests.unit import fake_instance
from pylxd import exceptions as lxdcore_exceptions
import six

from nova.virt.lxd import driver
from nova.virt.lxd import utils

MockResponse = collections.namedtuple('Response', ['status_code'])

MockContainer = collections.namedtuple('Container', ['name'])
MockContainerState = collections.namedtuple(
    'ContainerState', ['status_code', 'memory'])


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

        self.name = 'volume-00000001'
        self.location = '10.0.2.15:3260'
        self.iqn = 'iqn.2010-10.org.openstack:%s' % self.name
        self.vol = {'id': 1, 'name': self.name}
        self.uuid = '875a8070-d0b9-4949-8b31-104d125c9a64'
        self.user = 'foo'

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

        lxd_driver = driver.LXDDriver(None)
        lxd_driver.init_host(None)
        # XXX: rockstar (6 Jul 2016) - There are a number of XXX comments
        # related to these calls in spawn. They require some work before we
        # can take out these mocks and follow the real codepaths.
        lxd_driver.setup_image = mock.Mock()
        lxd_driver.vif_driver = mock.Mock()
        lxd_driver.firewall_driver = mock.Mock()
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

        lxd_driver = driver.LXDDriver(None)
        lxd_driver.init_host(None)
        lxd_driver.vif_driver = mock.Mock()
        lxd_driver.firewall_driver = mock.Mock()

        lxd_driver.cleanup(ctx, instance, network_info)

        lxd_driver.vif_driver.unplug.assert_called_once_with(
            instance, network_info[0])
        lxd_driver.firewall_driver.unfilter_instance.assert_called_once_with(
            instance, network_info)
        execute.assert_called_once_with(
            'chown', '-R', 'user:user', instance_dir, run_as_root=True)
        rmtree.assert_called_once_with(instance_dir)

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

    def _iscsi_connection(self, volume, location, iqn, auth=False,
                          transport=None):
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

    @mock.patch('os.readlink')
    def test_attach_volume(self, readlink):
        mock_profile = mock.Mock()
        self.client.profiles.get.return_value = mock_profile
        readlink.return_value = '/dev/sdc'
        ctx = context.get_admin_context()
        instance = fake_instance.fake_instance_obj(ctx, name='test')
        connection_info = self._iscsi_connection(self.vol, self.location,
                                                 self.iqn, auth=True)
        mountpoint = mock.Mock()

        lxd_driver = driver.LXDDriver(None)
        lxd_driver.init_host(None)

        lxd_driver.connector.connect_volume = mock.MagicMock()
        lxd_driver.attach_volume(ctx, connection_info, instance,
                                 mountpoint, None, None, None)

        lxd_driver.client.profiles.get.assert_called_once_with(instance.name)
        lxd_driver.connector.connect_volume.asert_called_once_with(
            connection_info['data'])

    def test_detatch_volume(self):
        mock_profile = mock.Mock()
        mock_profile.devices = {
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

        self.client.profiles.get.return_value = mock_profile
        ctx = context.get_admin_context()
        instance = fake_instance.fake_instance_obj(ctx, name='test')
        connection_info = self._iscsi_connection(self.vol, self.location,
                                                 self.iqn, auth=True)
        mountpoint = mock.Mock()

        lxd_driver = driver.LXDDriver(None)
        lxd_driver.init_host(None)

        lxd_driver.connector.disconnect_volume = mock.MagicMock()
        lxd_driver.detach_volume(connection_info, instance, mountpoint, None)

        lxd_driver.client.profiles.get.assert_called_once_with(instance.name)

        self.assertEqual(expected, mock_profile.devices)
