# Copyright 2015 Canonical Ltd
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

import inspect
import json
import os

import ddt
import mock
from nova.compute import arch
from nova.compute import hv_type
from nova.compute import power_state
from nova.compute import task_states
from nova.compute import vm_mode
from nova import exception
from nova import test
from nova.virt import fake
from nova.virt import hardware
from oslo_config import cfg
from pylxd import exceptions as lxd_exceptions
import six

from nclxd.nova.virt.lxd import container_ops
from nclxd.nova.virt.lxd import container_snapshot
from nclxd.nova.virt.lxd import container_utils
from nclxd.nova.virt.lxd import driver
from nclxd.nova.virt.lxd import host
from nclxd import tests


class LXDTestConfig(test.NoDBTestCase):

    def test_config(self):
        self.assertIsInstance(driver.CONF.lxd, cfg.ConfigOpts.GroupAttr)
        self.assertEqual(os.path.abspath('/var/lib/lxd'),
                         os.path.abspath(driver.CONF.lxd.root_dir))
        self.assertEqual(5, driver.CONF.lxd.timeout)
        self.assertEqual('nclxd-profile', driver.CONF.lxd.default_profile)


@ddt.ddt
@mock.patch.object(container_ops, 'CONF', tests.MockConf())
@mock.patch.object(container_utils, 'CONF', tests.MockConf())
@mock.patch.object(driver, 'CONF', tests.MockConf())
@mock.patch.object(host, 'CONF', tests.MockConf())
class LXDTestDriver(test.NoDBTestCase):

    @mock.patch.object(driver, 'CONF', tests.MockConf())
    def setUp(self):
        super(LXDTestDriver, self).setUp()
        self.ml = tests.lxd_mock()
        lxd_patcher = mock.patch('pylxd.api.API',
                                 mock.Mock(return_value=self.ml))
        lxd_patcher.start()
        self.addCleanup(lxd_patcher.stop)

        self.connection = driver.LXDDriver(fake.FakeVirtAPI())

    def test_capabilities(self):
        self.assertFalse(self.connection.capabilities['has_imagecache'])
        self.assertFalse(self.connection.capabilities['supports_recreate'])
        self.assertFalse(
            self.connection.capabilities['supports_migrate_to_same_host'])

    def test_init_host(self):
        self.assertEqual(
            True,
            self.connection.init_host(None)
        )

    def test_init_host_new_profile(self):
        self.ml.profile_list.return_value = []
        self.assertEqual(
            True,
            self.connection.init_host(None)
        )
        self.ml.profile_create.assert_called_once_with(
            {'name': 'fake_profile'})

    @tests.annotated_data(
        ('profile_fail', {'profile_list.side_effect':
                          lxd_exceptions.APIError('Fake', 500)}),
        ('no_ping', {'host_ping.return_value': False}),
        ('ping_fail', {'host_ping.side_effect':
                       lxd_exceptions.APIError('Fake', 500)}),
    )
    def test_init_host_fail(self, tag, config):
        self.ml.configure_mock(**config)
        self.assertRaises(
            exception.HostNotFound,
            self.connection.init_host,
            None
        )

    @tests.annotated_data(
        ('RUNNING', power_state.RUNNING),
        ('STOPPED', power_state.SHUTDOWN),
        ('STARTING', power_state.NOSTATE),
        ('STOPPING', power_state.SHUTDOWN),
        ('ABORTING', power_state.CRASHED),
        ('FREEZING', power_state.PAUSED),
        ('FROZEN', power_state.SUSPENDED),
        ('THAWED', power_state.PAUSED),
        ('PENDING', power_state.NOSTATE),
        ('Success', power_state.RUNNING),
        ('UNKNOWN', power_state.NOSTATE),
        (lxd_exceptions.APIError('Fake', 500), power_state.NOSTATE),
    )
    def test_get_info(self, side_effect, expected):
        instance = tests.MockInstance()
        self.ml.container_state.side_effect = [side_effect]
        self.assertEqual(hardware.InstanceInfo(state=expected, num_cpu=2),
                         self.connection.get_info(instance))

    @tests.annotated_data(
        (True, 'mock-instance-1'),
        (False, 'fake-instance'),
    )
    def test_instance_exists(self, expected, name):
        self.assertEqual(
            expected,
            self.connection.instance_exists(tests.MockInstance(name=name)))

    def test_estimate_instance_overhead(self):
        self.assertEqual(
            {'memory_mb': 0},
            self.connection.estimate_instance_overhead(mock.Mock()))

    def test_list_instances(self):
        self.assertEqual(['mock-instance-1', 'mock-instance-2'],
                         self.connection.list_instances())

    def test_list_instances_fail(self):
        self.ml.container_list.side_effect = (
            lxd_exceptions.APIError('Fake', 500))
        self.assertRaises(
            exception.NovaException,
            self.connection.list_instances
        )

    @tests.annotated_data(
        ('exists', [True], exception.InstanceExists),
        ('fail', lxd_exceptions.APIError('Fake', 500), exception.NovaException)
    )
    def test_spawn_defined(self, tag, side_effect, expected):
        instance = tests.MockInstance()
        self.ml.container_defined.side_effect = side_effect
        self.assertRaises(
            expected,
            self.connection.spawn,
            {}, instance, {}, [], 'secret')
        self.ml.container_defined.called_once_with('mock_instance')

    def test_spawn_new(self):
        context = mock.Mock()
        instance = tests.MockInstance()
        image_meta = mock.Mock()
        injected_files = mock.Mock()
        network_info = mock.Mock()
        block_device_info = mock.Mock()
        self.ml.container_defined.return_value = False
        with mock.patch.object(self.connection.container_ops,
                               'create_instance') as mc:
            self.assertEqual(
                None,
                self.connection.spawn(
                    context, instance, image_meta, injected_files, 'secret',
                    network_info, block_device_info))
            mc.assert_called_once_with(
                context, instance, image_meta, injected_files, 'secret',
                network_info, block_device_info, None, False)

    def test_destroy_fail(self):
        instance = tests.MockInstance()
        self.ml.container_destroy.side_effect = (
            lxd_exceptions.APIError('Fake', 500))
        self.assertRaises(
            exception.NovaException,
            self.connection.destroy,
            {}, instance, [])
        self.ml.container_destroy.assert_called_with('mock_instance')

    @mock.patch('shutil.rmtree')
    @tests.annotated_data(
        ('ack', (202, {}), False),
        ('ack-rmtree', (202, {}), True),
        ('not-found', lxd_exceptions.APIError('Not found', 404), False),
    )
    def test_destroy(self, tag, side_effect, exists, mr):
        instance = tests.MockInstance()
        self.ml.container_destroy.side_effect = [side_effect]
        with mock.patch('os.path.exists', return_value=exists):
            self.assertEqual(
                None,
                self.connection.destroy({}, instance, [])
            )
            self.ml.container_destroy.assert_called_once_with('mock_instance')
            if exists:
                mr.assert_called_once_with(
                    '/fake/instances/path/mock_instance')
            else:
                self.assertFalse(mr.called)

    @mock.patch('os.path.exists', mock.Mock(return_value=True))
    @mock.patch('shutil.rmtree')
    def test_cleanup(self, mr):
        instance = tests.MockInstance()
        self.assertEqual(
            None,
            self.connection.cleanup({}, instance, [], [], None, None, None))
        mr.assert_called_once_with(
            '/fake/instances/path/mock_instance')

    @mock.patch('six.moves.builtins.open')
    @mock.patch.object(container_ops.utils, 'execute')
    @mock.patch('pwd.getpwuid', mock.Mock(return_value=mock.Mock(pw_uid=1234)))
    @mock.patch('os.getuid', mock.Mock())
    def test_get_console_output(self, me, mo):
        instance = tests.MockInstance()
        mo.return_value.__enter__.return_value = six.BytesIO(b'fake contents')
        self.assertEqual(b'fake contents',
                         self.connection.get_console_output({}, instance))
        calls = [
            mock.call('chown', '1234:1234',
                      '/fake/lxd/root/containers/mock_instance/console.log',
                      run_as_root=True),
            mock.call('chmod', '755',
                      '/fake/lxd/root/containers/mock_instance',
                      run_as_root=True)
        ]
        self.assertEqual(calls, me.call_args_list)

    @mock.patch.object(host.compute_utils, 'get_machine_ips')
    @tests.annotated_data(
        ('found', ['1.2.3.4']),
        ('not-found', ['4.3.2.1']),
    )
    def test_get_host_ip_addr(self, tag, return_value, mi):
        mi.return_value = return_value
        self.assertEqual('1.2.3.4', self.connection.get_host_ip_addr())

    @mock.patch('six.moves.builtins.open')
    @tests.annotated_data(
        {'tag': 'single-if',
         'net': 'Head\nHead\n\neth0:\n',
         'expected_if': 'eth1',
         'config': {'config': {}, 'devices': {}}},
        {'tag': 'multi-if',
         'net': 'Head\nHead\nbr0:\neth0:\neth1:\neth2:\n',
         'expected_if': 'eth2',
         'config': {'config': {}, 'devices': {}}},
        {'tag': 'firewall-fail',
         'firewall_setup': exception.NovaException,
         'success': False},
        {'tag': 'config-fail',
         'config': lxd_exceptions.APIError('Fake', 500),
         'success': False},
        {'tag': 'info-fail',
         'config': {'config': {}, 'devices': {}},
         'info': lxd_exceptions.APIError('Fake', 500),
         'success': False},
    )
    def test_attach_interface(self, mo, tag, net='', config={},
                              info={'init': 1}, firewall_setup=None,
                              expected_if='', success=True):
        instance = tests.MockInstance()
        vif = {
            'id': '0123456789abcdef',
            'address': '00:11:22:33:44:55',
        }
        self.ml.get_container_config.side_effect = [config]
        self.ml.container_info.side_effect = [info]
        mo.return_value = six.moves.cStringIO(net)
        with mock.patch.object(self.connection.container_ops,
                               'vif_driver') as mv, (
            mock.patch.object((self.connection.container_ops
                               .firewall_driver), 'firewall_driver')) as mf:
            manager = mock.Mock()
            manager.attach_mock(mv, 'vif')
            manager.attach_mock(mf, 'firewall')
            mf.setup_basic_filtering.side_effect = [firewall_setup]
            self.assertEqual(
                None,
                self.connection.attach_interface(instance, {}, vif)
            )
            calls = [
                mock.call.vif.plug(instance, vif),
                mock.call.firewall.setup_basic_filtering(instance, vif)
            ]
            if not success:
                calls.append(mock.call.vif.unplug(instance, vif))
            self.assertEqual(calls, manager.method_calls)
        if success:
            self.ml.container_update.assert_called_once_with(
                'mock_instance',
                {'config': {},
                 'devices': {
                    'qbr0123456789a': {
                        'hwaddr': '00:11:22:33:44:55',
                        'type': 'nic',
                        'name': expected_if,
                        'parent': 'qbr0123456789a',
                        'nictype': 'bridged'}}})

    def test_detach_interface_fail(self):
        instance = tests.MockInstance()
        vif = mock.Mock()
        with mock.patch.object(self.connection.container_ops,
                               'vif_driver') as mv:
            mv.unplug.side_effect = [TypeError]

            self.assertRaises(
                TypeError,
                self.connection.detach_interface,
                instance, vif)

    @tests.annotated_data(
        ('ok', True),
        ('nova-exc', exception.NovaException),
    )
    def test_detach_interface(self, tag, side_effect):
        instance = tests.MockInstance()
        vif = mock.Mock()
        with mock.patch.object(self.connection.container_ops,
                               'vif_driver') as mv:
            mv.unplug.side_effect = [side_effect]
            self.assertEqual(
                None,
                self.connection.detach_interface(instance, vif)
            )
            mv.unplug.assert_called_once_with(instance, vif)

    @mock.patch.object(container_snapshot, 'IMAGE_API')
    def test_snapshot(self, mi):
        context = mock.Mock()
        instance = tests.MockInstance()
        image_id = 'mock_image'

        mi.get.return_value = {'name': 'mock_snapshot'}
        self.ml.container_snapshot_create.return_value = (
            200, {'operation': '/1.0/operations/0123456789'})
        self.ml.container_stop.return_value = (
            200, {'operation': '/1.0/operations/1234567890'})
        self.ml.container_start.return_value = (
            200, {'operation': '/1.0/operations/2345678901'})
        self.ml.container_publish.return_value = (
            200, {'metadata': {'fingerprint': 'abcdef0123456789'}})

        manager = mock.Mock()
        manager.attach_mock(mi, 'image')
        manager.attach_mock(self.ml, 'lxd')

        self.assertEqual(
            None,
            self.connection.snapshot(
                context, instance, image_id, manager.update)
        )
        calls = [
            mock.call.update(task_state=task_states.IMAGE_PENDING_UPLOAD),
            mock.call.image.get(context, 'mock_image'),
            mock.call.lxd.container_snapshot_create(
                'mock_instance',
                {'name': 'mock_snapshot', 'stateful': False}),
            mock.call.lxd.wait_container_operation('0123456789', 200, 20),
            mock.call.lxd.container_stop('mock_instance', 20),
            mock.call.lxd.wait_container_operation('1234567890', 200, 20),
            mock.call.lxd.container_publish(
                {'source': {'name': 'mock_instance/mock_snapshot',
                            'type': 'snapshot'}}),
            mock.call.lxd.alias_create(
                {'name': 'mock_snapshot', 'target': 'abcdef0123456789'}),
            mock.call.lxd.image_export('abcdef0123456789'),
            mock.call.image.update(
                context, 'mock_image',
                {'name': 'mock_snapshot', 'disk_format': 'raw',
                 'container_format': 'bare', 'properties': {}},
                self.ml.image_export.return_value),
            mock.call.update(task_state=task_states.IMAGE_UPLOADING,
                             expected_state=task_states.IMAGE_PENDING_UPLOAD),
            mock.call.lxd.container_start('mock_instance', 20),
            mock.call.lxd.wait_container_operation('2345678901', 200, 20),
        ]
        self.assertEqual(calls, manager.method_calls)

    def test_rescue_fail(self):
        instance = tests.MockInstance()
        self.ml.container_defined.return_value = True
        self.assertRaises(exception.NovaException,
                          self.connection.rescue,
                          {}, instance, [], {}, 'secret')

    def test_rescue(self):
        context = mock.Mock()
        instance = tests.MockInstance()
        image_meta = mock.Mock()
        network_info = mock.Mock()
        self.ml.container_defined.return_value = False
        with mock.patch.object(self.connection.container_ops, 'spawn') as ms:
            mgr = mock.Mock()
            mgr.attach_mock(ms, 'spawn')
            mgr.attach_mock(self.ml.container_stop, 'stop')
            self.assertEqual(None,
                             self.connection.rescue(context,
                                                    instance,
                                                    network_info,
                                                    image_meta,
                                                    'secret'))
            calls = [
                mock.call.stop('mock_instance', 20),
                mock.call.spawn(
                    context, instance, image_meta, [], 'secret', network_info,
                    name_label='mock_instance-rescue', rescue=True)
            ]
            self.assertEqual(calls, mgr.method_calls)

    def test_container_unrescue(self):
        instance = tests.MockInstance()
        network_info = mock.Mock()
        self.assertEqual(None,
                         self.connection.unrescue(instance,
                                                  network_info))
        calls = [
            mock.call.container_start('mock_instance', 20),
            mock.call.container_destroy('mock_instance-rescue')
        ]
        self.assertEqual(calls, self.ml.method_calls)

    @mock.patch.object(container_ops.utils, 'execute',
                       mock.Mock(return_value=('', True)))
    def test_get_available_resource_fail(self):
        self.assertRaises(
            exception.NovaException,
            self.connection.get_available_resource,
            None)

    @mock.patch('platform.node', mock.Mock(return_value='fake_hostname'))
    @mock.patch('os.statvfs', return_value=mock.Mock(f_blocks=131072000,
                                                     f_bsize=8192,
                                                     f_bavail=65536000))
    @mock.patch('six.moves.builtins.open')
    @mock.patch.object(container_ops.utils, 'execute')
    def test_get_available_resource(self, me, mo, ms):
        me.return_value = ('Model name:          Fake CPU\n'
                           'Vendor ID:           FakeVendor\n'
                           'Socket(s):           10\n'
                           'Core(s) per socket:  5\n'
                           'Thread(s) per core:  4\n',
                           None)
        meminfo = mock.MagicMock()
        meminfo.__enter__.return_value = six.moves.cStringIO(
            'MemTotal: 10240000 kB\n'
            'MemFree:   2000000 kB\n'
            'Buffers:     24000 kB\n'
            'Cached:      24000 kB\n')

        mo.side_effect = [
            six.moves.cStringIO('flags: fake flag goes here'),
            meminfo,
        ]
        value = self.connection.get_available_resource(None)
        value['cpu_info'] = json.loads(value['cpu_info'])
        value['supported_instances'] = json.loads(value['supported_instances'])
        expected = {'cpu_info': {'arch': 'x86_64',
                                 'features': 'fake flag goes here',
                                 'model': 'Fake CPU',
                                 'topology': {'cores': '5',
                                              'sockets': '10',
                                              'threads': '4'},
                                 'vendor': 'FakeVendor'},
                    'hypervisor_hostname': 'fake_hostname',
                    'hypervisor_type': 'lxd',
                    'hypervisor_version': '011',
                    'local_gb': 1000,
                    'local_gb_used': 500,
                    'memory_mb': 10000,
                    'memory_mb_used': 8000,
                    'numa_topology': None,
                    'supported_instances': [[arch.I686, hv_type.LXC,
                                             vm_mode.EXE],
                                            [arch.X86_64, hv_type.LXC,
                                             vm_mode.EXE]],
                    'vcpus': 200,
                    'vcpus_used': 0}
        self.assertEqual(expected, value)
        me.assert_called_once_with('lscpu')
        self.assertEqual([mock.call('/proc/cpuinfo', 'r'),
                          mock.call('/proc/meminfo')],
                         mo.call_args_list)
        ms.assert_called_once_with('/fake/lxd/root')

    # methods that simply proxy some arguments through
    simple_methods = (
        ('reboot', 'container_reboot',
         ({}, tests.MockInstance(), [], None, None, None),
         ('mock_instance',)),
        ('pause', 'container_freeze',
         (tests.MockInstance(),),
         ('mock_instance', 20)),
        ('power_off', 'container_stop',
         (tests.MockInstance(),),
         ('mock_instance', 20)),
        ('power_on', 'container_start',
         ({}, tests.MockInstance(), []),
         ('mock_instance', 20),
         False),
    )

    @tests.annotated_data(*simple_methods)
    def test_simple_fail(self, name, lxd_name, args, call_args,
                         ignore_404=True):
        call = getattr(self.connection, name)
        lxd_call = getattr(self.ml, lxd_name)
        lxd_call.side_effect = lxd_exceptions.APIError('Fake', 500)
        self.assertRaises(
            exception.NovaException,
            call, *args)
        lxd_call.assert_called_once_with(*call_args)

    @tests.annotated_data(*simple_methods)
    def test_simple_notfound(self, name, lxd_name, args, call_args,
                             ignore_404=True):
        call = getattr(self.connection, name)
        lxd_call = getattr(self.ml, lxd_name)
        lxd_call.side_effect = lxd_exceptions.APIError('Fake', 404)
        if ignore_404:
            self.assertEqual(
                None,
                call(*args))
        else:
            self.assertRaises(
                exception.NovaException,
                call, *args)
        lxd_call.assert_called_once_with(*call_args)

    @tests.annotated_data(*simple_methods)
    def test_simple(self, name, lxd_name, args, call_args, ignore_404=True):
        call = getattr(self.connection, name)
        lxd_call = getattr(self.ml, lxd_name)
        self.assertEqual(
            lxd_call.return_value,
            call(*args))
        lxd_call.assert_called_once_with(*call_args)


@ddt.ddt
class LXDTestDriverNoops(test.NoDBTestCase):

    def setUp(self):
        super(LXDTestDriverNoops, self).setUp()
        self.connection = driver.LXDDriver(fake.FakeVirtAPI())

    @ddt.data(
        'list_instance_uuids',
        'get_diagnostics',
        'get_instance_diagnostics',
        'get_all_bw_counters',
        'get_all_volume_usage',
        'attach_volume',
        'detach_volume',
        'migrate_disk_and_power_off',
        'finish_migration',
        'confirm_migration',
        'finish_revert_migration',
        'unpause',
        'suspend',
        'resume',
        'soft_delete',
        'pre_live_migration',
        'live_migration',
        'rollback_live_migration_at_destination',
        'post_live_migration_at_source',
        'post_live_migration_at_destination',
        'check_instance_shared_storage_local',
        'check_instance_shared_storage_remote',
        'check_can_live_migrate_destination',
        'check_can_live_migrate_destination_cleanup',
        'check_can_live_migrate_source',
        'get_instance_disk_info',
        'poll_rebooting_instances',
        'host_power_action',
        'host_maintenance_mode',
        'set_host_enabled',
        'block_stats',
        'add_to_aggregate',
        'remove_from_aggregate',
        'undo_aggregate_operation',
        'get_volume_connector',
        'volume_snapshot_create',
        'volume_snapshot_delete',
        'quiesce',
        'unquiesce',
    )
    def test_notimplemented(self, method):
        call = getattr(self.connection, method)
        argspec = inspect.getargspec(call)
        self.assertRaises(
            NotImplementedError,
            call,
            *([None] * (len(argspec.args) - 1)))

    @ddt.data(
        'post_interrupted_snapshot_cleanup',
        'post_live_migration',
        'check_instance_shared_storage_cleanup',
        'manage_image_cache',
    )
    def test_pass(self, method):
        call = getattr(self.connection, method)
        argspec = inspect.getargspec(call)
        self.assertEqual(
            None,
            call(*([None] * (len(argspec.args) - 1))))

    @tests.annotated_data(
        ('deallocate_networks_on_reschedule', False),
        ('macs_for_instance', None),
        ('get_per_instance_usage', {}),
        ('instance_on_disk', False),
    )
    def test_return(self, method, expected):
        call = getattr(self.connection, method)
        argspec = inspect.getargspec(call)
        self.assertEqual(
            expected,
            call(*([None] * (len(argspec.args) - 1))))
