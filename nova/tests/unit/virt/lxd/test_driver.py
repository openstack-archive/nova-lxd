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
import base64
from contextlib import closing

import eventlet
from oslo_config import cfg
from oslo_serialization import jsonutils
import mock
from nova import context
from nova import exception
from nova import utils
from nova import test
from nova.compute import manager
from nova.compute import power_state
from nova.compute import vm_states
from nova.network import model as network_model
from nova.tests.unit import fake_instance
from pylxd import exceptions as lxdcore_exceptions
import six

from nova.virt.lxd import common
from nova.virt.lxd import driver

MockResponse = collections.namedtuple('Response', ['status_code'])

MockContainer = collections.namedtuple('Container', ['name'])
MockContainerState = collections.namedtuple(
    'ContainerState', ['status', 'memory', 'status_code'])

_VIF = {
    'devname': 'lol0', 'type': 'bridge', 'id': '0123456789abcdef',
    'address': 'ca:fe:de:ad:be:ef'}


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


class GetPowerStateTest(test.NoDBTestCase):
    """Tests for nova.virt.lxd.driver.LXDDriver."""

    def test_running(self):
        state = driver._get_power_state(100)
        self.assertEqual(power_state.RUNNING, state)

    def test_shutdown(self):
        state = driver._get_power_state(102)
        self.assertEqual(power_state.SHUTDOWN, state)

    def test_nostate(self):
        state = driver._get_power_state(105)
        self.assertEqual(power_state.NOSTATE, state)

    def test_crashed(self):
        state = driver._get_power_state(108)
        self.assertEqual(power_state.CRASHED, state)

    def test_suspended(self):
        state = driver._get_power_state(109)
        self.assertEqual(power_state.SUSPENDED, state)

    def test_unknown(self):
        self.assertRaises(ValueError, driver._get_power_state, 69)


class LXDDriverTest(test.NoDBTestCase):
    """Tests for nova.virt.lxd.driver.LXDDriver."""

    def setUp(self):
        super(LXDDriverTest, self).setUp()

        self.Client_patcher = mock.patch('nova.virt.lxd.driver.pylxd.Client')
        self.Client = self.Client_patcher.start()

        self.client = mock.Mock()
        self.client.host_info = {
            'environment': {
                'storage': 'zfs',
            }
        }
        self.Client.return_value = self.client

        self.patchers = []

        CONF_patcher = mock.patch('nova.virt.lxd.driver.CONF')
        self.patchers.append(CONF_patcher)
        self.CONF = CONF_patcher.start()
        self.CONF.instances_path = '/path/to/instances'
        self.CONF.my_ip = '0.0.0.0'
        self.CONF.config_drive_format = 'iso9660'

        # XXX: rockstar (03 Nov 2016) - This should be removed once
        # everything is where it should live.
        CONF2_patcher = mock.patch('nova.virt.lxd.driver.nova.conf.CONF')
        self.patchers.append(CONF2_patcher)
        self.CONF2 = CONF2_patcher.start()
        self.CONF2.lxd.root_dir = '/lxd'
        self.CONF2.lxd.pool = None
        self.CONF2.instances_path = '/i'

        # LXDDriver._after_reboot reads from the database and syncs container
        # state. These tests can't read from the database.
        after_reboot_patcher = mock.patch(
            'nova.virt.lxd.driver.LXDDriver._after_reboot')
        self.patchers.append(after_reboot_patcher)
        self.after_reboot = after_reboot_patcher.start()

        bdige_patcher = mock.patch(
            'nova.virt.lxd.driver.driver.block_device_info_get_ephemerals')
        self.patchers.append(bdige_patcher)
        self.block_device_info_get_ephemerals = bdige_patcher.start()
        self.block_device_info_get_ephemerals.return_value = []

        vif_driver_patcher = mock.patch(
            'nova.virt.lxd.driver.lxd_vif.LXDGenericVifDriver')
        self.patchers.append(vif_driver_patcher)
        self.LXDGenericVifDriver = vif_driver_patcher.start()
        self.vif_driver = mock.Mock()
        self.LXDGenericVifDriver.return_value = self.vif_driver

        vif_gc_patcher = mock.patch('nova.virt.lxd.driver.lxd_vif.get_config')
        self.patchers.append(vif_gc_patcher)
        self.get_config = vif_gc_patcher.start()
        self.get_config.return_value = {
            'mac_address': '00:11:22:33:44:55', 'bridge': 'qbr0123456789a',
        }

        # NOTE: mock out fileutils to ensure that unit tests don't try
        #       to manipulate the filesystem (breaks in package builds).
        driver.fileutils = mock.Mock()

    def tearDown(self):
        super(LXDDriverTest, self).tearDown()
        self.Client_patcher.stop()
        for patcher in self.patchers:
            patcher.stop()

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
            'Running', {'usage': 4000, 'usage_peak': 4500}, 100)
        self.client.containers.get.return_value = container

        ctx = context.get_admin_context()
        instance = fake_instance.fake_instance_obj(
            ctx, name='test', memory_mb=0)
        lxd_driver = driver.LXDDriver(None)
        lxd_driver.init_host(None)

        info = lxd_driver.get_info(instance)

        self.assertEqual(power_state.RUNNING, info.state)

    def test_list_instances(self):
        self.client.containers.all.return_value = [
            MockContainer('mock-instance-1'),
            MockContainer('mock-instance-2'),
        ]
        lxd_driver = driver.LXDDriver(None)
        lxd_driver.init_host(None)

        instances = lxd_driver.list_instances()

        self.assertEqual(['mock-instance-1', 'mock-instance-2'], instances)

    @mock.patch('nova.virt.lxd.driver.IMAGE_API')
    @mock.patch('nova.virt.lxd.driver.lockutils.lock')
    def test_spawn_unified_image(self, lock, IMAGE_API=None):
        def image_get(*args, **kwargs):
            raise lxdcore_exceptions.LXDAPIException(MockResponse(404))
        self.client.images.get_by_alias.side_effect = image_get
        self.client.images.exists.return_value = False
        image = {'name': mock.Mock(), 'disk_format': 'raw'}
        IMAGE_API.get.return_value = image

        def download_unified(*args, **kwargs):
            # unified image with metadata
            # structure is gzipped tarball, content:
            # /
            #  metadata.yaml
            #  rootfs/
            unified_tgz = 'H4sIALpegVkAA+3SQQ7CIBCFYY7CCXRAppwHo66sTVpYeHsh0a'\
                          'Ru1A2Lxv/bDGQmYZLHeM7plHLa3dN4NX1INQyhVRdV1vXFuIML'\
                          '4lVVopF28cZKp33elCWn2VpTjuWWy4e5L/2NmqcpX5Z91zdawD'\
                          'HqT/kHrf/E+Xo0Vrtu9fTn+QMAAAAAAAAAAAAAAADYrgfk/3zn'\
                          'ACgAAA=='
            with closing(open(kwargs['dest_path'], 'wb+')) as img:
                img.write(base64.b64decode(unified_tgz))
        IMAGE_API.download = download_unified
        self.test_spawn()

    @mock.patch('nova.virt.configdrive.required_by')
    def test_spawn(self, configdrive, neutron_failure=None):
        def container_get(*args, **kwargs):
            raise lxdcore_exceptions.LXDAPIException(MockResponse(404))
        self.client.containers.get.side_effect = container_get
        configdrive.return_value = False
        container = mock.Mock()
        self.client.containers.create.return_value = container

        ctx = context.get_admin_context()
        instance = fake_instance.fake_instance_obj(
            ctx, name='test', memory_mb=0)
        image_meta = mock.Mock()
        injected_files = mock.Mock()
        admin_password = mock.Mock()
        allocations = mock.Mock()
        network_info = [_VIF]
        block_device_info = mock.Mock()
        virtapi = manager.ComputeVirtAPI(mock.MagicMock())

        lxd_driver = driver.LXDDriver(virtapi)
        lxd_driver.init_host(None)
        # XXX: rockstar (6 Jul 2016) - There are a number of XXX comments
        # related to these calls in spawn. They require some work before we
        # can take out these mocks and follow the real codepaths.
        lxd_driver.firewall_driver = mock.Mock()

        lxd_driver.spawn(
            ctx, instance, image_meta, injected_files, admin_password,
            allocations, network_info, block_device_info)

        self.vif_driver.plug.assert_called_once_with(
            instance, network_info[0])
        fd = lxd_driver.firewall_driver
        fd.setup_basic_filtering.assert_called_once_with(
            instance, network_info)
        fd.apply_instance_filter.assert_called_once_with(
            instance, network_info)
        container.start.assert_called_once_with(wait=True)

    def test_spawn_already_exists(self):
        """InstanceExists is raised if the container already exists."""
        ctx = context.get_admin_context()
        instance = fake_instance.fake_instance_obj(
            ctx, name='test', memory_mb=0)
        image_meta = mock.Mock()
        injected_files = mock.Mock()
        admin_password = mock.Mock()
        allocations = mock.Mock()

        lxd_driver = driver.LXDDriver(None)
        lxd_driver.init_host(None)

        self.assertRaises(
            exception.InstanceExists,

            lxd_driver.spawn,
            ctx, instance, image_meta, injected_files, admin_password,
            allocations, None, None)

    @mock.patch('nova.virt.configdrive.required_by')
    def test_spawn_with_configdrive(self, configdrive):
        def container_get(*args, **kwargs):
            raise lxdcore_exceptions.LXDAPIException(MockResponse(404))

        self.client.containers.get.side_effect = container_get
        configdrive.return_value = True

        ctx = context.get_admin_context()
        instance = fake_instance.fake_instance_obj(
            ctx, name='test', memory_mb=0)
        image_meta = mock.Mock()
        injected_files = mock.Mock()
        admin_password = mock.Mock()
        allocations = mock.Mock()
        network_info = [_VIF]
        block_device_info = mock.Mock()
        virtapi = manager.ComputeVirtAPI(mock.MagicMock())

        lxd_driver = driver.LXDDriver(virtapi)
        lxd_driver.init_host(None)
        # XXX: rockstar (6 Jul 2016) - There are a number of XXX comments
        # related to these calls in spawn. They require some work before we
        # can take out these mocks and follow the real codepaths.
        lxd_driver.firewall_driver = mock.Mock()
        lxd_driver._add_configdrive = mock.Mock()

        lxd_driver.spawn(
            ctx, instance, image_meta, injected_files, admin_password,
            allocations, network_info, block_device_info)

        self.vif_driver.plug.assert_called_once_with(
            instance, network_info[0])
        fd = lxd_driver.firewall_driver
        fd.setup_basic_filtering.assert_called_once_with(
            instance, network_info)
        fd.apply_instance_filter.assert_called_once_with(
            instance, network_info)
        configdrive.assert_called_once_with(instance)
        lxd_driver.client.profiles.get.assert_called_once_with(instance.name)

    @mock.patch('nova.virt.configdrive.required_by')
    def test_spawn_profile_fail(self, configdrive, neutron_failure=None):
        """Cleanup is called when profile creation fails."""
        def container_get(*args, **kwargs):
            raise lxdcore_exceptions.LXDAPIException(MockResponse(404))

        def profile_create(*args, **kwargs):
            raise lxdcore_exceptions.LXDAPIException(MockResponse(500))
        self.client.containers.get.side_effect = container_get
        self.client.profiles.create.side_effect = profile_create
        configdrive.return_value = False
        ctx = context.get_admin_context()
        instance = fake_instance.fake_instance_obj(
            ctx, name='test', memory_mb=0)
        image_meta = mock.Mock()
        injected_files = mock.Mock()
        admin_password = mock.Mock()
        allocations = mock.Mock()
        network_info = [_VIF]
        block_device_info = mock.Mock()
        virtapi = manager.ComputeVirtAPI(mock.MagicMock())

        lxd_driver = driver.LXDDriver(virtapi)
        lxd_driver.init_host(None)
        lxd_driver.cleanup = mock.Mock()

        self.assertRaises(
            lxdcore_exceptions.LXDAPIException,
            lxd_driver.spawn,
            ctx, instance, image_meta, injected_files, admin_password,
            allocations, network_info, block_device_info)
        lxd_driver.cleanup.assert_called_once_with(
            ctx, instance, network_info, block_device_info)

    @mock.patch('nova.virt.configdrive.required_by')
    def test_spawn_container_fail(self, configdrive, neutron_failure=None):
        """Cleanup is called when container creation fails."""
        def container_get(*args, **kwargs):
            raise lxdcore_exceptions.LXDAPIException(MockResponse(404))

        def container_create(*args, **kwargs):
            raise lxdcore_exceptions.LXDAPIException(MockResponse(500))
        self.client.containers.get.side_effect = container_get
        self.client.containers.create.side_effect = container_create
        configdrive.return_value = False
        ctx = context.get_admin_context()
        instance = fake_instance.fake_instance_obj(
            ctx, name='test', memory_mb=0)
        image_meta = mock.Mock()
        injected_files = mock.Mock()
        admin_password = mock.Mock()
        allocations = mock.Mock()
        network_info = [_VIF]
        block_device_info = mock.Mock()
        virtapi = manager.ComputeVirtAPI(mock.MagicMock())

        lxd_driver = driver.LXDDriver(virtapi)
        lxd_driver.init_host(None)
        lxd_driver.cleanup = mock.Mock()

        self.assertRaises(
            lxdcore_exceptions.LXDAPIException,
            lxd_driver.spawn,
            ctx, instance, image_meta, injected_files, admin_password,
            allocations, network_info, block_device_info)
        lxd_driver.cleanup.assert_called_once_with(
            ctx, instance, network_info, block_device_info)

    @mock.patch('nova.virt.configdrive.required_by', return_value=False)
    def test_spawn_container_cleanup_fail(self, configdrive):
        """Cleanup is called but also fail when container creation fails."""
        self.client.containers.get.side_effect = (
            lxdcore_exceptions.LXDAPIException(MockResponse(404)))
        container = mock.Mock()
        self.client.containers.create.return_value = container

        ctx = context.get_admin_context()
        instance = fake_instance.fake_instance_obj(
            ctx, name='test', memory_mb=0)
        image_meta = mock.Mock()
        injected_files = mock.Mock()
        admin_password = mock.Mock()
        allocations = mock.Mock()
        network_info = [_VIF]
        block_device_info = mock.Mock()
        virtapi = manager.ComputeVirtAPI(mock.MagicMock())

        lxd_driver = driver.LXDDriver(virtapi)
        lxd_driver.init_host(None)

        container.start.side_effect = (
            lxdcore_exceptions.LXDAPIException(MockResponse(500)))
        lxd_driver.cleanup = mock.Mock()
        lxd_driver.cleanup.side_effect = Exception("a bad thing")

        self.assertRaises(
            lxdcore_exceptions.LXDAPIException,
            lxd_driver.spawn,
            ctx, instance, image_meta, injected_files, admin_password,
            allocations, network_info, block_device_info)
        lxd_driver.cleanup.assert_called_once_with(
            ctx, instance, network_info, block_device_info)

    def test_spawn_container_start_fail(self, neutron_failure=None):
        def container_get(*args, **kwargs):
            raise lxdcore_exceptions.LXDAPIException(MockResponse(404))

        def side_effect(*args, **kwargs):
            raise lxdcore_exceptions.LXDAPIException(MockResponse(200))

        self.client.containers.get.side_effect = container_get
        container = mock.Mock()
        ctx = context.get_admin_context()
        instance = fake_instance.fake_instance_obj(
            ctx, name='test', memory_mb=0)
        image_meta = mock.Mock()
        injected_files = mock.Mock()
        admin_password = mock.Mock()
        allocations = mock.Mock()
        network_info = [_VIF]
        block_device_info = mock.Mock()
        virtapi = manager.ComputeVirtAPI(mock.MagicMock())

        lxd_driver = driver.LXDDriver(virtapi)
        lxd_driver.init_host(None)
        lxd_driver.cleanup = mock.Mock()
        lxd_driver.client.containers.create = mock.Mock(
            side_effect=side_effect)
        container.start.side_effect = side_effect

        self.assertRaises(
            lxdcore_exceptions.LXDAPIException,
            lxd_driver.spawn,
            ctx, instance, image_meta, injected_files, admin_password,
            allocations, network_info, block_device_info)
        lxd_driver.cleanup.assert_called_once_with(
            ctx, instance, network_info, block_device_info)

    def _test_spawn_instance_with_network_events(self, neutron_failure=None):
        generated_events = []

        def wait_timeout():
            event = mock.MagicMock()
            if neutron_failure == 'timeout':
                raise eventlet.timeout.Timeout()
            elif neutron_failure == 'error':
                event.status = 'failed'
            else:
                event.status = 'completed'
            return event

        def fake_prepare(instance, event_name):
            m = mock.MagicMock()
            m.instance = instance
            m.event_name = event_name
            m.wait.side_effect = wait_timeout
            generated_events.append(m)
            return m

        virtapi = manager.ComputeVirtAPI(mock.MagicMock())
        prepare = virtapi._compute.instance_events.prepare_for_instance_event
        prepare.side_effect = fake_prepare
        drv = driver.LXDDriver(virtapi)

        instance_href = fake_instance.fake_instance_obj(
            context.get_admin_context(), name='test', memory_mb=0)

        @mock.patch.object(drv, 'plug_vifs')
        @mock.patch('nova.virt.configdrive.required_by')
        def test_spawn(configdrive, plug_vifs):
            def container_get(*args, **kwargs):
                raise lxdcore_exceptions.LXDAPIException(MockResponse(404))
            self.client.containers.get.side_effect = container_get
            configdrive.return_value = False

            ctx = context.get_admin_context()
            instance = fake_instance.fake_instance_obj(
                ctx, name='test', memory_mb=0)
            image_meta = mock.Mock()
            injected_files = mock.Mock()
            admin_password = mock.Mock()
            allocations = mock.Mock()
            network_info = [_VIF]
            block_device_info = mock.Mock()

            drv.init_host(None)
            drv.spawn(
                ctx, instance, image_meta, injected_files, admin_password,
                allocations, network_info, block_device_info)

        test_spawn()

        if cfg.CONF.vif_plugging_timeout and utils.is_neutron():
            prepare.assert_has_calls([
                mock.call(instance_href, 'network-vif-plugged-vif1'),
                mock.call(instance_href, 'network-vif-plugged-vif2')])
            for event in generated_events:
                if neutron_failure and generated_events.index(event) != 0:
                    self.assertEqual(0, event.call_count)
        else:
            self.assertEqual(0, prepare.call_count)

    @mock.patch('nova.utils.is_neutron', return_value=True)
    def test_spawn_instance_with_network_events(self, is_neutron):
        self.flags(vif_plugging_timeout=0)
        self._test_spawn_instance_with_network_events()

    @mock.patch('nova.utils.is_neutron', return_value=True)
    def test_spawn_instance_with_events_neutron_failed_nonfatal_timeout(
            self, is_neutron):
        self.flags(vif_plugging_timeout=0)
        self.flags(vif_plugging_is_fatal=False)
        self._test_spawn_instance_with_network_events(
            neutron_failure='timeout')

    @mock.patch('nova.virt.lxd.driver.lockutils.lock')
    def test_destroy(self, lock):
        mock_container = mock.Mock()
        mock_container.status = 'Running'
        self.client.containers.get.return_value = mock_container
        ctx = context.get_admin_context()
        instance = fake_instance.fake_instance_obj(
            ctx, name='test', memory_mb=0)
        network_info = [_VIF]

        lxd_driver = driver.LXDDriver(None)
        lxd_driver.init_host(None)
        lxd_driver.cleanup = mock.Mock()  # There is a separate cleanup test

        lxd_driver.destroy(ctx, instance, network_info)

        lxd_driver.cleanup.assert_called_once_with(
            ctx, instance, network_info, None)
        lxd_driver.client.containers.get.assert_called_once_with(instance.name)
        mock_container.stop.assert_called_once_with(wait=True)
        mock_container.delete.assert_called_once_with(wait=True)

    @mock.patch('nova.virt.lxd.driver.lockutils.lock')
    def test_destroy_when_in_rescue(self, lock):
        mock_stopped_container = mock.Mock()
        mock_stopped_container.status = 'Stopped'
        mock_rescued_container = mock.Mock()
        mock_rescued_container.status = 'Running'
        ctx = context.get_admin_context()
        instance = fake_instance.fake_instance_obj(
            ctx, name='test', memory_mb=0)
        network_info = [_VIF]

        lxd_driver = driver.LXDDriver(None)
        lxd_driver.init_host(None)
        lxd_driver.cleanup = mock.Mock()

        # set the vm_state on the fake instance to RESCUED
        instance.vm_state = vm_states.RESCUED

        # set up the containers.get to return the stopped container and then
        # the rescued container
        self.client.containers.get.side_effect = [
            mock_stopped_container, mock_rescued_container]

        lxd_driver.destroy(ctx, instance, network_info)

        lxd_driver.cleanup.assert_called_once_with(
            ctx, instance, network_info, None)
        lxd_driver.client.containers.get.assert_has_calls([
            mock.call(instance.name),
            mock.call('{}-rescue'.format(instance.name))])
        mock_stopped_container.stop.assert_not_called()
        mock_stopped_container.delete.assert_called_once_with(wait=True)
        mock_rescued_container.stop.assert_called_once_with(wait=True)
        mock_rescued_container.delete.assert_called_once_with(wait=True)

    @mock.patch('nova.virt.lxd.driver.lockutils.lock')
    def test_destroy_without_instance(self, lock):
        def side_effect(*args, **kwargs):
            raise lxdcore_exceptions.LXDAPIException(MockResponse(404))
        self.client.containers.get.side_effect = side_effect

        ctx = context.get_admin_context()
        instance = fake_instance.fake_instance_obj(
            ctx, name='test', memory_mb=0)
        network_info = [_VIF]

        lxd_driver = driver.LXDDriver(None)
        lxd_driver.init_host(None)
        lxd_driver.cleanup = mock.Mock()  # There is a separate cleanup test

        lxd_driver.destroy(ctx, instance, network_info)
        lxd_driver.cleanup.assert_called_once_with(
            ctx, instance, network_info, None)

    @mock.patch('nova.virt.lxd.driver.network')
    @mock.patch('os.path.exists', mock.Mock(return_value=True))
    @mock.patch('pwd.getpwuid')
    @mock.patch('shutil.rmtree')
    @mock.patch.object(driver.utils, 'execute')
    def test_cleanup(self, execute, rmtree, getpwuid, _):
        mock_profile = mock.Mock()
        self.client.profiles.get.return_value = mock_profile
        pwuid = mock.Mock()
        pwuid.pw_name = 'user'
        getpwuid.return_value = pwuid

        ctx = context.get_admin_context()
        instance = fake_instance.fake_instance_obj(
            ctx, name='test', memory_mb=0)
        network_info = [_VIF]
        instance_dir = common.InstanceAttributes(instance).instance_dir
        block_device_info = mock.Mock()

        lxd_driver = driver.LXDDriver(None)
        lxd_driver.init_host(None)
        lxd_driver.firewall_driver = mock.Mock()

        lxd_driver.cleanup(ctx, instance, network_info, block_device_info)

        self.vif_driver.unplug.assert_called_once_with(
            instance, network_info[0])
        lxd_driver.firewall_driver.unfilter_instance.assert_called_once_with(
            instance, network_info)
        execute.assert_called_once_with(
            'chown', '-R', 'user:user', instance_dir, run_as_root=True)
        rmtree.assert_called_once_with(instance_dir)
        mock_profile.delete.assert_called_once_with()

    def test_reboot(self):
        ctx = context.get_admin_context()
        instance = fake_instance.fake_instance_obj(
            ctx, name='test', memory_mb=0)

        lxd_driver = driver.LXDDriver(None)
        lxd_driver.init_host(None)

        lxd_driver.reboot(ctx, instance, None, None)

        self.client.containers.get.assert_called_once_with(instance.name)

    @mock.patch('nova.virt.lxd.driver.network')
    @mock.patch('pwd.getpwuid', mock.Mock(return_value=mock.Mock(pw_uid=1234)))
    @mock.patch('os.getuid', mock.Mock())
    @mock.patch('os.path.exists', mock.Mock(return_value=True))
    @mock.patch('six.moves.builtins.open')
    @mock.patch.object(driver.utils, 'execute')
    def test_get_console_output(self, execute, _open, _):
        ctx = context.get_admin_context()
        instance = fake_instance.fake_instance_obj(
            ctx, name='test', memory_mb=0)
        expected_calls = [
            mock.call(
                'chown', '1234:1234', '/var/log/lxd/{}/console.log'.format(
                    instance.name),
                run_as_root=True),
            mock.call(
                'chmod', '755', '/lxd/containers/{}'.format(
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
            'parent': 'tin0123456789a',
            'nictype': 'physical',
            'type': 'nic',
        }

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
        }
        self.client.profiles.get.return_value = profile

        ctx = context.get_admin_context()
        instance = fake_instance.fake_instance_obj(
            ctx, name='test', memory_mb=0)
        image_meta = None
        vif = {
            'id': '0123456789abcdef',
            'type': network_model.VIF_TYPE_OVS,
            'address': '00:11:22:33:44:55',
            'network': {
                'bridge': 'fakebr'},
            'devname': 'tap0123456789a'}

        lxd_driver = driver.LXDDriver(None)
        lxd_driver.init_host(None)
        lxd_driver.firewall_driver = mock.Mock()

        lxd_driver.attach_interface(ctx, instance, image_meta, vif)

        self.assertTrue('tap0123456789a' in profile.devices)
        self.assertEqual(expected, profile.devices['tap0123456789a'])
        profile.save.assert_called_once_with(wait=True)

    def test_detach_interface_legacy(self):
        profile = mock.Mock()
        profile.devices = {
            'eth0': {
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
        self.client.profiles.get.return_value = profile

        ctx = context.get_admin_context()
        instance = fake_instance.fake_instance_obj(
            ctx, name='test', memory_mb=0)
        vif = {
            'id': '0123456789abcdef',
            'type': network_model.VIF_TYPE_OVS,
            'address': '00:11:22:33:44:55',
            'network': {
                'bridge': 'fakebr'}}

        lxd_driver = driver.LXDDriver(None)
        lxd_driver.init_host(None)

        lxd_driver.detach_interface(ctx, instance, vif)

        self.vif_driver.unplug.assert_called_once_with(
            instance, vif)
        self.assertEqual(['root'], sorted(profile.devices.keys()))
        profile.save.assert_called_once_with(wait=True)

    def test_detach_interface(self):
        profile = mock.Mock()
        profile.devices = {
            'tap0123456789a': {
                'nictype': 'physical',
                'parent': 'tin0123456789a',
                'hwaddr': '00:11:22:33:44:55',
                'type': 'nic'
            },
            'root': {
                'path': '/',
                'type': 'disk'
            },
        }
        self.client.profiles.get.return_value = profile

        ctx = context.get_admin_context()
        instance = fake_instance.fake_instance_obj(
            ctx, name='test', memory_mb=0)
        vif = {
            'id': '0123456789abcdef',
            'type': network_model.VIF_TYPE_OVS,
            'address': '00:11:22:33:44:55',
            'network': {
                'bridge': 'fakebr'}}

        lxd_driver = driver.LXDDriver(None)
        lxd_driver.init_host(None)

        lxd_driver.detach_interface(ctx, instance, vif)

        self.vif_driver.unplug.assert_called_once_with(
            instance, vif)
        self.assertEqual(['root'], sorted(profile.devices.keys()))
        profile.save.assert_called_once_with(wait=True)

    def test_detach_interface_not_found(self):
        self.client.profiles.get.side_effect = lxdcore_exceptions.NotFound(
            "404")

        ctx = context.get_admin_context()
        instance = fake_instance.fake_instance_obj(
            ctx, name='test', memory_mb=0)
        vif = {
            'id': '0123456789abcdef',
            'type': network_model.VIF_TYPE_OVS,
            'address': '00:11:22:33:44:55',
            'network': {
                'bridge': 'fakebr'}}

        lxd_driver = driver.LXDDriver(None)
        lxd_driver.init_host(None)

        lxd_driver.detach_interface(ctx, instance, vif)

        self.vif_driver.unplug.assert_called_once_with(
            instance, vif)

    def test_migrate_disk_and_power_off(self):
        container = mock.Mock()
        self.client.containers.get.return_value = container
        profile = mock.Mock()
        self.client.profiles.get.return_value = profile

        ctx = context.get_admin_context()
        instance = fake_instance.fake_instance_obj(
            ctx, name='test', memory_mb=0)
        dest = '0.0.0.0'
        flavor = mock.Mock()
        network_info = []

        lxd_driver = driver.LXDDriver(None)
        lxd_driver.init_host(None)

        lxd_driver.migrate_disk_and_power_off(
            ctx, instance, dest, flavor, network_info)

        profile.save.assert_called_once_with()
        container.stop.assert_called_once_with(wait=True)

    def test_migrate_disk_and_power_off_different_host(self):
        """Migrating to a different host only shuts down the container."""
        container = mock.Mock()
        self.client.containers.get.return_value = container

        ctx = context.get_admin_context()
        instance = fake_instance.fake_instance_obj(
            ctx, name='test', memory_mb=0)
        dest = '0.0.0.1'
        flavor = mock.Mock()
        network_info = []

        lxd_driver = driver.LXDDriver(None)
        lxd_driver.init_host(None)

        lxd_driver.migrate_disk_and_power_off(
            ctx, instance, dest, flavor, network_info)

        self.assertEqual(0, self.client.profiles.get.call_count)
        container.stop.assert_called_once_with(wait=True)

    @mock.patch('nova.virt.lxd.driver.network')
    @mock.patch('os.major')
    @mock.patch('os.minor')
    @mock.patch('os.stat')
    @mock.patch('os.path.realpath')
    def test_attach_volume(self, realpath, stat, minor, major, _):
        profile = mock.Mock()
        self.client.profiles.get.return_value = profile
        realpath.return_value = '/dev/sdc'
        stat.return_value.st_rdev = 2080
        minor.return_value = 32
        major.return_value = 8
        ctx = context.get_admin_context()
        instance = fake_instance.fake_instance_obj(
            ctx, name='test', memory_mb=0)
        connection_info = fake_connection_info(
            {'id': 1, 'name': 'volume-00000001'},
            '10.0.2.15:3260', 'iqn.2010-10.org.openstack:volume-00000001',
            auth=True)
        mountpoint = '/dev/sdd'

        driver.brick_get_connector = mock.MagicMock()
        driver.brick_get_connector_properties = mock.MagicMock()
        lxd_driver = driver.LXDDriver(None)
        lxd_driver.init_host(None)
        # driver.brick_get_connector = mock.MagicMock()
        # lxd_driver.storage_driver.connect_volume = mock.MagicMock()
        lxd_driver.attach_volume(
            ctx, connection_info, instance, mountpoint, None, None, None)

        lxd_driver.client.profiles.get.assert_called_once_with(instance.name)
        # driver.brick_get_connector.connect_volume.assert_called_once_with(
        #     connection_info['data'])
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
        instance = fake_instance.fake_instance_obj(
            ctx, name='test', memory_mb=0)
        connection_info = fake_connection_info(
            {'id': 1, 'name': 'volume-00000001'},
            '10.0.2.15:3260', 'iqn.2010-10.org.openstack:volume-00000001',
            auth=True)
        mountpoint = mock.Mock()

        lxd_driver = driver.LXDDriver(None)
        lxd_driver.init_host(None)

        driver.brick_get_connector = mock.MagicMock()
        driver.brick_get_connector_properties = mock.MagicMock()
        lxd_driver.detach_volume(ctx, connection_info, instance,
                                 mountpoint, None)

        lxd_driver.client.profiles.get.assert_called_once_with(instance.name)

        self.assertEqual(expected, profile.devices)
        profile.save.assert_called_once_with()

    def test_pause(self):
        container = mock.Mock()
        self.client.containers.get.return_value = container
        ctx = context.get_admin_context()
        instance = fake_instance.fake_instance_obj(
            ctx, name='test', memory_mb=0)

        lxd_driver = driver.LXDDriver(None)
        lxd_driver.init_host(None)

        lxd_driver.pause(instance)

        self.client.containers.get.assert_called_once_with(instance.name)
        container.freeze.assert_called_once_with(wait=True)

    def test_unpause(self):
        container = mock.Mock()
        self.client.containers.get.return_value = container
        ctx = context.get_admin_context()
        instance = fake_instance.fake_instance_obj(
            ctx, name='test', memory_mb=0)

        lxd_driver = driver.LXDDriver(None)
        lxd_driver.init_host(None)

        lxd_driver.unpause(instance)

        self.client.containers.get.assert_called_once_with(instance.name)
        container.unfreeze.assert_called_once_with(wait=True)

    def test_suspend(self):
        container = mock.Mock()
        self.client.containers.get.return_value = container
        ctx = context.get_admin_context()
        instance = fake_instance.fake_instance_obj(
            ctx, name='test', memory_mb=0)

        lxd_driver = driver.LXDDriver(None)
        lxd_driver.init_host(None)

        lxd_driver.suspend(ctx, instance)

        self.client.containers.get.assert_called_once_with(instance.name)
        container.freeze.assert_called_once_with(wait=True)

    def test_resume(self):
        container = mock.Mock()
        self.client.containers.get.return_value = container
        ctx = context.get_admin_context()
        instance = fake_instance.fake_instance_obj(
            ctx, name='test', memory_mb=0)

        lxd_driver = driver.LXDDriver(None)
        lxd_driver.init_host(None)

        lxd_driver.resume(ctx, instance, None, None)

        self.client.containers.get.assert_called_once_with(instance.name)
        container.unfreeze.assert_called_once_with(wait=True)

    def test_resume_state_on_host_boot(self):
        container = mock.Mock()
        state = mock.Mock()
        state.memory = dict({'usage': 0, 'usage_peak': 0})
        state.status_code = 102
        container.state.return_value = state
        self.client.containers.get.return_value = container
        ctx = context.get_admin_context()
        instance = fake_instance.fake_instance_obj(
            ctx, name='test', memory_mb=0)

        lxd_driver = driver.LXDDriver(None)
        lxd_driver.init_host(None)

        lxd_driver.resume_state_on_host_boot(ctx, instance, None, None)
        container.start.assert_called_once_with(wait=True)

    def test_rescue(self):
        profile = mock.Mock()
        profile.devices = {
            'root': {
                'type': 'disk',
                'path': '/',
                'size': '1GB'
            }
        }
        container = mock.Mock()
        self.client.profiles.get.return_value = profile
        self.client.containers.get.return_value = container
        ctx = context.get_admin_context()
        instance = fake_instance.fake_instance_obj(
            ctx, name='test', memory_mb=0)
        profile.name = instance.name
        network_info = [_VIF]
        image_meta = mock.Mock()
        rescue_password = mock.Mock()
        rescue = '%s-rescue' % instance.name

        lxd_driver = driver.LXDDriver(None)
        lxd_driver.init_host(None)

        lxd_driver.rescue(
            ctx, instance, network_info, image_meta, rescue_password)

        lxd_driver.client.containers.get.assert_called_once_with(instance.name)
        container.rename.assert_called_once_with(rescue, wait=True)
        lxd_driver.client.profiles.get.assert_called_once_with(instance.name)
        lxd_driver.client.containers.create.assert_called_once_with(
            {'name': instance.name, 'profiles': [profile.name],
             'source': {'type': 'image', 'alias': None},
             }, wait=True)

        self.assertTrue('rescue' in profile.devices)

    def test_unrescue(self):
        container = mock.Mock()
        container.status = 'Running'
        self.client.containers.get.return_value = container
        profile = mock.Mock()
        profile.devices = {
            'root': {
                'type': 'disk',
                'path': '/',
                'size': '1GB'
            },
            'rescue': {
                'source': '/path',
                'path': '/mnt',
                'type': 'disk'
            }
        }
        self.client.profiles.get.return_value = profile

        ctx = context.get_admin_context()
        instance = fake_instance.fake_instance_obj(
            ctx, name='test', memory_mb=0)
        network_info = [_VIF]
        rescue = '%s-rescue' % instance.name

        lxd_driver = driver.LXDDriver(None)
        lxd_driver.init_host(None)

        lxd_driver.unrescue(instance, network_info)

        container.stop.assert_called_once_with(wait=True)
        container.delete.assert_called_once_with(wait=True)
        lxd_driver.client.profiles.get.assert_called_once_with(instance.name)
        profile.save.assert_called_once_with()
        lxd_driver.client.containers.get.assert_called_with(rescue)
        container.rename.assert_called_once_with(instance.name, wait=True)
        container.start.assert_called_once_with(wait=True)
        self.assertTrue('rescue' not in profile.devices)

    def test_power_off(self):
        container = mock.Mock()
        container.status = 'Running'
        self.client.containers.get.return_value = container
        ctx = context.get_admin_context()
        instance = fake_instance.fake_instance_obj(
            ctx, name='test', memory_mb=0)

        lxd_driver = driver.LXDDriver(None)
        lxd_driver.init_host(None)
        lxd_driver.power_off(instance)

        self.client.containers.get.assert_called_once_with(instance.name)
        container.stop.assert_called_once_with(wait=True)

    def test_power_on(self):
        container = mock.Mock()
        container.status = 'Stopped'
        self.client.containers.get.return_value = container
        ctx = context.get_admin_context()
        instance = fake_instance.fake_instance_obj(
            ctx, name='test', memory_mb=0)

        lxd_driver = driver.LXDDriver(None)
        lxd_driver.init_host(None)
        lxd_driver.power_on(ctx, instance, None)

        self.client.containers.get.assert_called_once_with(instance.name)
        container.start.assert_called_once_with(wait=True)

    @mock.patch('socket.gethostname', mock.Mock(return_value='fake_hostname'))
    @mock.patch('os.statvfs', return_value=mock.Mock(
        f_blocks=131072000, f_bsize=8192, f_bavail=65536000))
    @mock.patch('nova.virt.lxd.driver.open')
    @mock.patch.object(driver.utils, 'execute')
    def test_get_available_resource(self, execute, open, statvfs):
        expected = {
            'cpu_info': {
                "features": "fake flag goes here",
                "model": "Fake CPU",
                "topology": {"sockets": "10", "threads": "4", "cores": "5"},
                "arch": "x86_64", "vendor": "FakeVendor"
            },
            'hypervisor_hostname': 'fake_hostname',
            'hypervisor_type': 'lxd',
            'hypervisor_version': '011',
            'local_gb': 1000,
            'local_gb_used': 500,
            'memory_mb': 10000,
            'memory_mb_used': 8000,
            'numa_topology': None,
            'supported_instances': [
                ('i686', 'lxd', 'exe'),
                ('x86_64', 'lxd', 'exe'),
                ('i686', 'lxc', 'exe'),
                ('x86_64', 'lxc', 'exe')],
            'vcpus': 200,
            'vcpus_used': 0}

        execute.return_value = (
            'Model name:          Fake CPU\n'
            'Vendor ID:           FakeVendor\n'
            'Socket(s):           10\n'
            'Core(s) per socket:  5\n'
            'Thread(s) per core:  4\n\n',
            None)
        meminfo = mock.MagicMock()
        meminfo.__enter__.return_value = six.moves.cStringIO(
            'MemTotal: 10240000 kB\n'
            'MemFree:   2000000 kB\n'
            'Buffers:     24000 kB\n'
            'Cached:      24000 kB\n')

        open.side_effect = [
            six.moves.cStringIO('flags: fake flag goes here\n'
                                'processor: 2\n'
                                '\n'),
            meminfo,
        ]
        lxd_config = {
            'environment': {
                'storage': 'dir',
            },
            'config': {}
        }
        lxd_driver = driver.LXDDriver(None)
        lxd_driver.client = mock.MagicMock()
        lxd_driver.client.host_info = lxd_config
        value = lxd_driver.get_available_resource(None)
        # This is funky, but json strings make for fragile tests.
        value['cpu_info'] = jsonutils.loads(value['cpu_info'])

        self.assertEqual(expected, value)

    @mock.patch.object(driver.utils, 'execute')
    def test__get_zpool_info(self, execute):
        # first test with a zpool; should make 3 calls to execute
        execute.side_effect = [
            ('1\n', None),
            ('2\n', None),
            ('3\n', None)
        ]
        expected = {
            'total': 1,
            'used': 2,
            'available': 3,
        }
        self.assertEqual(expected, driver._get_zpool_info('lxd'))

        # then test with a zfs dataset; should just be 2 calls
        execute.reset_mock()
        execute.side_effect = [
            ('10\n', None),
            ('20\n', None),
        ]
        expected = {
            'total': 30,
            'used': 10,
            'available': 20,
        }
        self.assertEqual(expected, driver._get_zpool_info('lxd/dataset'))

    @mock.patch('socket.gethostname', mock.Mock(return_value='fake_hostname'))
    @mock.patch('nova.virt.lxd.driver.open')
    @mock.patch.object(driver.utils, 'execute')
    def test_get_available_resource_zfs(self, execute, open):
        expected = {
            'cpu_info': {
                "features": "fake flag goes here",
                "model": "Fake CPU",
                "topology": {"sockets": "10", "threads": "4", "cores": "5"},
                "arch": "x86_64", "vendor": "FakeVendor"
            },
            'hypervisor_hostname': 'fake_hostname',
            'hypervisor_type': 'lxd',
            'hypervisor_version': '011',
            'local_gb': 2222,
            'local_gb_used': 200,
            'memory_mb': 10000,
            'memory_mb_used': 8000,
            'numa_topology': None,
            'supported_instances': [
                ('i686', 'lxd', 'exe'),
                ('x86_64', 'lxd', 'exe'),
                ('i686', 'lxc', 'exe'),
                ('x86_64', 'lxc', 'exe')],
            'vcpus': 200,
            'vcpus_used': 0}

        execute.side_effect = [
            ('Model name:          Fake CPU\n'
             'Vendor ID:           FakeVendor\n'
             'Socket(s):           10\n'
             'Core(s) per socket:  5\n'
             'Thread(s) per core:  4\n\n',
             None),
            ('2385940232273\n', None),  # 2.17T
            ('215177861529\n', None),   # 200.4G
            ('1979120929996\n', None)   # 1.8T
        ]

        meminfo = mock.MagicMock()
        meminfo.__enter__.return_value = six.moves.cStringIO(
            'MemTotal: 10240000 kB\n'
            'MemFree:   2000000 kB\n'
            'Buffers:     24000 kB\n'
            'Cached:      24000 kB\n')

        open.side_effect = [
            six.moves.cStringIO('flags: fake flag goes here\n'
                                'processor: 2\n'
                                '\n'),
            meminfo,
        ]
        lxd_config = {
            'environment': {
                'storage': 'zfs',
            },
            'config': {
                'storage.zfs_pool_name': 'lxd',
            }
        }
        lxd_driver = driver.LXDDriver(None)
        lxd_driver.client = mock.MagicMock()
        lxd_driver.client.host_info = lxd_config
        value = lxd_driver.get_available_resource(None)
        # This is funky, but json strings make for fragile tests.
        value['cpu_info'] = jsonutils.loads(value['cpu_info'])

        self.assertEqual(expected, value)

    def test_refresh_instance_security_rules(self):
        ctx = context.get_admin_context()
        instance = fake_instance.fake_instance_obj(
            ctx, name='test', memory_mb=0)
        firewall = mock.Mock()

        lxd_driver = driver.LXDDriver(None)
        lxd_driver.firewall_driver = firewall
        lxd_driver.refresh_instance_security_rules(instance)

        firewall.refresh_instance_security_rules.assert_called_once_with(
            instance)

    def test_ensure_filtering_rules_for_instance(self):
        ctx = context.get_admin_context()
        instance = fake_instance.fake_instance_obj(
            ctx, name='test', memory_mb=0)
        firewall = mock.Mock()
        network_info = object()

        lxd_driver = driver.LXDDriver(None)
        lxd_driver.firewall_driver = firewall
        lxd_driver.ensure_filtering_rules_for_instance(instance, network_info)

        firewall.ensure_filtering_rules_for_instance.assert_called_once_with(
            instance, network_info)

    def test_filter_defer_apply_on(self):
        firewall = mock.Mock()

        lxd_driver = driver.LXDDriver(None)
        lxd_driver.firewall_driver = firewall
        lxd_driver.filter_defer_apply_on()

        firewall.filter_defer_apply_on.assert_called_once_with()

    def test_filter_defer_apply_off(self):
        firewall = mock.Mock()

        lxd_driver = driver.LXDDriver(None)
        lxd_driver.firewall_driver = firewall
        lxd_driver.filter_defer_apply_off()

        firewall.filter_defer_apply_off.assert_called_once_with()

    def test_unfilter_instance(self):
        ctx = context.get_admin_context()
        instance = fake_instance.fake_instance_obj(
            ctx, name='test', memory_mb=0)
        firewall = mock.Mock()
        network_info = object()

        lxd_driver = driver.LXDDriver(None)
        lxd_driver.firewall_driver = firewall
        lxd_driver.unfilter_instance(instance, network_info)

        firewall.unfilter_instance.assert_called_once_with(
            instance, network_info)

    @mock.patch.object(driver.utils, 'execute')
    def test_get_host_uptime(self, execute):
        expected = '00:00:00 up 0 days, 0:00 , 0 users, load average: 0'
        execute.return_value = (expected, 'stderr')

        lxd_driver = driver.LXDDriver(None)
        result = lxd_driver.get_host_uptime()

        self.assertEqual(expected, result)

    @mock.patch('nova.virt.lxd.driver.psutil.cpu_times')
    @mock.patch('nova.virt.lxd.driver.open')
    @mock.patch.object(driver.utils, 'execute')
    def test_get_host_cpu_stats(self, execute, open, cpu_times):
        cpu_times.return_value = [
            '1', 'b', '2', '3', '4'
        ]
        execute.return_value = (
            'Model name:          Fake CPU\n'
            'Vendor ID:           FakeVendor\n'
            'Socket(s):           10\n'
            'Core(s) per socket:  5\n'
            'Thread(s) per core:  4\n\n',
            None)
        open.return_value = six.moves.cStringIO(
            'flags: fake flag goes here\n'
            'processor: 2\n\n')

        expected = {
            'user': 1, 'iowait': 4, 'frequency': 0, 'kernel': 2, 'idle': 3}

        lxd_driver = driver.LXDDriver(None)
        result = lxd_driver.get_host_cpu_stats()

        self.assertEqual(expected, result)

    def test_get_volume_connector(self):
        expected = {
            'host': 'fakehost',
            'initiator': 'fake',
            'ip': self.CONF.my_block_storage_ip
        }

        ctx = context.get_admin_context()
        instance = fake_instance.fake_instance_obj(
            ctx, name='test', memory_mb=0)

        lxd_driver = driver.LXDDriver(None)
        result = lxd_driver.get_volume_connector(instance)

        self.assertEqual(expected, result)

    @mock.patch('nova.virt.lxd.driver.socket.gethostname')
    def test_get_available_nodes(self, gethostname):
        gethostname.return_value = 'nova-lxd'

        expected = ['nova-lxd']

        lxd_driver = driver.LXDDriver(None)
        result = lxd_driver.get_available_nodes()

        self.assertEqual(expected, result)

    @mock.patch('nova.virt.lxd.driver.IMAGE_API')
    @mock.patch('nova.virt.lxd.driver.lockutils.lock')
    def test_snapshot(self, lock, IMAGE_API):
        update_task_state_expected = [
            mock.call(task_state='image_pending_upload'),
            mock.call(
                expected_state='image_pending_upload',
                task_state='image_uploading'),
        ]

        container = mock.Mock()
        self.client.containers.get.return_value = container
        image = mock.Mock()
        container.publish.return_value = image
        data = mock.Mock()
        image.export.return_value = data
        ctx = context.get_admin_context()
        instance = fake_instance.fake_instance_obj(
            ctx, name='test', memory_mb=0)
        image_id = mock.Mock()
        update_task_state = mock.Mock()
        snapshot = {'name': mock.Mock()}
        IMAGE_API.get.return_value = snapshot

        lxd_driver = driver.LXDDriver(None)
        lxd_driver.init_host(None)

        lxd_driver.snapshot(ctx, instance, image_id, update_task_state)

        self.assertEqual(
            update_task_state_expected, update_task_state.call_args_list)
        IMAGE_API.get.assert_called_once_with(ctx, image_id)
        IMAGE_API.update.assert_called_once_with(
            ctx, image_id, {
                'name': snapshot['name'],
                'disk_format': 'raw',
                'container_format': 'bare'},
            data)

    def test_finish_revert_migration(self):
        ctx = context.get_admin_context()
        instance = fake_instance.fake_instance_obj(
            ctx, name='test', memory_mb=0)
        network_info = []

        container = mock.Mock()
        self.client.containers.get.return_value = container

        lxd_driver = driver.LXDDriver(None)
        lxd_driver.init_host(None)

        lxd_driver.finish_revert_migration(ctx, instance, network_info)

        container.start.assert_called_once_with(wait=True)

    def test_check_can_live_migrate_destination(self):
        ctx = context.get_admin_context()
        instance = fake_instance.fake_instance_obj(
            ctx, name='test', memory_mb=0)
        src_compute_info = mock.Mock()
        dst_compute_info = mock.Mock()

        def container_get(*args, **kwargs):
            raise lxdcore_exceptions.LXDAPIException(MockResponse(404))
        self.client.containers.get.side_effect = container_get

        lxd_driver = driver.LXDDriver(None)
        lxd_driver.init_host(None)

        retval = lxd_driver.check_can_live_migrate_destination(
            ctx, instance, src_compute_info, dst_compute_info)

        self.assertIsInstance(retval, driver.LXDLiveMigrateData)

    def test_confirm_migration(self):
        migration = mock.Mock()
        instance = fake_instance.fake_instance_obj(
            context.get_admin_context, name='test', memory_mb=0)
        network_info = []
        profile = mock.Mock()
        container = mock.Mock()
        self.client.profiles.get.return_value = profile
        self.client.containers.get.return_value = container

        lxd_driver = driver.LXDDriver(None)
        lxd_driver.init_host(None)

        lxd_driver.confirm_migration(migration, instance, network_info)

        profile.delete.assert_called_once_with()
        container.delete.assert_called_once_with(wait=True)

    def test_post_live_migration(self):
        ctx = context.get_admin_context()
        instance = fake_instance.fake_instance_obj(
            ctx, name='test', memory_mb=0)
        container = mock.Mock()
        self.client.containers.get.return_value = container

        lxd_driver = driver.LXDDriver(None)
        lxd_driver.init_host(None)

        lxd_driver.post_live_migration(context, instance, None)

        container.delete.assert_called_once_with(wait=True)

    def test_post_live_migration_at_source(self):
        ctx = context.get_admin_context()
        instance = fake_instance.fake_instance_obj(
            ctx, name='test', memory_mb=0)
        network_info = []
        profile = mock.Mock()
        self.client.profiles.get.return_value = profile

        lxd_driver = driver.LXDDriver(None)
        lxd_driver.cleanup = mock.Mock()
        lxd_driver.init_host(None)

        lxd_driver.post_live_migration_at_source(
            ctx, instance, network_info)

        profile.delete.assert_called_once_with()
        lxd_driver.cleanup.assert_called_once_with(ctx, instance, network_info)
