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
import platform
from pylxd.deprecated import exceptions as lxd_exceptions

import ddt
import mock
from oslo_config import cfg
import six

from nova.compute import arch
from nova.compute import hv_type
from nova.compute import power_state
from nova.compute import vm_mode
from nova import exception
from nova import test
from nova.virt import fake
from nova.virt import hardware

from nova_lxd.nova.virt.lxd import driver
from nova_lxd.nova.virt.lxd import host
from nova_lxd.nova.virt.lxd import operations as container_ops
from nova_lxd.nova.virt.lxd import session
from nova_lxd.nova.virt.lxd import utils as container_dir
from nova_lxd.tests import stubs


class LXDTestConfig(test.NoDBTestCase):

    def test_config(self):
        self.assertIsInstance(driver.CONF.lxd, cfg.ConfigOpts.GroupAttr)
        self.assertEqual(os.path.abspath('/var/lib/lxd'),
                         os.path.abspath(driver.CONF.lxd.root_dir))
        self.assertEqual(-1, driver.CONF.lxd.timeout)


@ddt.ddt
@mock.patch.object(container_ops, 'CONF', stubs.MockConf())
@mock.patch.object(container_dir, 'CONF', stubs.MockConf())
@mock.patch.object(driver, 'CONF', stubs.MockConf())
@mock.patch.object(host, 'CONF', stubs.MockConf())
class LXDTestDriver(test.NoDBTestCase):

    @mock.patch.object(driver, 'CONF', stubs.MockConf())
    def setUp(self):
        super(LXDTestDriver, self).setUp()
        self.ml = stubs.lxd_mock()
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

    @stubs.annotated_data(
        ('no_ping', {'host_ping.return_value': False}),
        ('ping_fail', {'host_ping.side_effect': (lxd_exceptions.
                                                 APIError('Fake',
                                                          500))}),
    )
    def test_init_host_fail(self, tag, config):
        self.ml.configure_mock(**config)
        self.assertRaises(
            exception.HostNotFound,
            self.connection.init_host,
            None
        )

    @stubs.annotated_data(
        ('running', {'state': 200, 'mem': 0, 'max_mem': 0},
         power_state.RUNNING),
        ('shutdown', {'state': 102, 'mem': 0, 'max_mem': 0},
         power_state.SHUTDOWN),
        ('crashed', {'state': 108, 'mem': 0, 'max_mem': 0},
         power_state.CRASHED),
        ('suspend', {'state': 109, 'mem': 0, 'max_mem': 0},
         power_state.SUSPENDED),
        ('no_state', {'state': 401, 'mem': 0, 'max_mem': 0},
         power_state.NOSTATE),
    )
    def test_get_info(self, tag, side_effect, expected):
        instance = stubs._fake_instance()
        with mock.patch.object(session.LXDAPISession,
                               "container_state",
                               ) as state:
            state.return_value = side_effect
            info = self.connection.get_info(instance)
            self.assertEqual(dir(hardware.InstanceInfo(state=expected,
                                                       num_cpu=2)), dir(info))

    @stubs.annotated_data(
        (True, 'mock-instance-1'),
        (False, 'fake-instance'),
    )
    def test_instance_exists(self, expected, name):
        self.assertEqual(
            expected,
            self.connection.instance_exists(stubs.MockInstance(name=name)))

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

    @stubs.annotated_data(
        ('exists', [True], exception.InstanceExists),
        ('fail', lxd_exceptions.APIError('Fake', 500), exception.NovaException)
    )
    def test_spawn_defined(self, tag, side_effect, expected):
        instance = stubs.MockInstance()
        self.ml.container_defined.side_effect = side_effect
        self.assertRaises(
            expected,
            self.connection.spawn,
            {}, instance, {}, [], 'secret')
        self.ml.container_defined.called_once_with('mock_instance')

    @stubs.annotated_data(
        ('undefined', False),
        ('404', lxd_exceptions.APIError('Not found', 404)),
    )
    @mock.patch('oslo_concurrency.lockutils.lock')
    def test_spawn_new(self, tag, side_effect, mc):
        context = mock.Mock()
        instance = stubs.MockInstance()
        image_meta = mock.Mock()
        injected_files = mock.Mock()
        network_info = mock.Mock()
        block_device_info = mock.Mock()
        self.ml.container_defined.side_effect = [side_effect]

        with test.nested(
                mock.patch.object(self.connection.container_ops,
                                  'spawn'),
        ) as (
                create_container
        ):
            self.connection.spawn(context, instance, image_meta,
                                  injected_files, None, network_info,
                                  block_device_info)
            self.assertTrue(create_container)

    def test_destroy_fail(self):
        instance = stubs._fake_instance()
        context = mock.Mock()
        network_info = mock.Mock()
        self.ml.container_destroy.side_effect = (
            lxd_exceptions.APIError('Fake', 500))
        with test.nested(
            mock.patch.object(session.LXDAPISession,
                              'container_destroy'),
            mock.patch.object(session.LXDAPISession,
                              'container_stop'),
            mock.patch.object(self.connection, 'cleanup'),
            mock.patch.object(container_ops.LXDContainerOperations,
                              'unplug_vifs'),

        ) as (
            container_destroy,
            container_stop,
            cleanup,
            unplug_vifs
        ):
            self.connection.destroy(context, instance, network_info)

    def test_destroy(self):
        instance = stubs._fake_instance()
        context = mock.Mock()
        network_info = mock.Mock()
        with test.nested(
                mock.patch.object(session.LXDAPISession,
                                  'container_stop'),
                mock.patch.object(session.LXDAPISession,
                                  'container_destroy'),
                mock.patch.object(self.connection,
                                  'cleanup'),
                mock.patch.object(container_ops.LXDContainerOperations,
                                  'unplug_vifs'),
        ) as (
                container_stop,
                container_destroy,
                cleanup,
                unplug_vifs
        ):
            self.connection.destroy(context, instance, network_info)
            self.assertTrue(container_stop)
            self.assertTrue(container_destroy)
            self.assertTrue(cleanup)
            unplug_vifs.assert_called_with(instance, network_info)

    @mock.patch('os.path.exists', mock.Mock(return_value=True))
    @mock.patch('shutil.rmtree')
    @mock.patch('pwd.getpwuid', mock.Mock(return_value=mock.Mock(pw_uid=1234)))
    @mock.patch.object(container_ops.utils, 'execute')
    def test_cleanup(self, mr, mu):
        instance = stubs.MockInstance()
        self.assertEqual(
            None,
            self.connection.cleanup({}, instance, [], [], None, None, None))

    @mock.patch('six.moves.builtins.open')
    @mock.patch.object(container_ops.utils, 'execute')
    @mock.patch('pwd.getpwuid', mock.Mock(return_value=mock.Mock(pw_uid=1234)))
    @mock.patch('os.getuid', mock.Mock())
    @mock.patch('os.path.exists', mock.Mock(return_value=True))
    def test_get_console_output(self, me, mo):
        instance = stubs.MockInstance()
        mo.return_value.__enter__.return_value = six.BytesIO(b'fake contents')
        self.assertEqual(b'fake contents',
                         self.connection.get_console_output({}, instance))
        calls = [
            mock.call('chown', '1234:1234',
                      '/var/log/lxd/fake-uuid/console.log',
                      run_as_root=True),
            mock.call('chmod', '755',
                      '/fake/lxd/root/containers/fake-uuid',
                      run_as_root=True)
        ]
        self.assertEqual(calls, me.call_args_list)

    @mock.patch.object(host.compute_utils, 'get_machine_ips')
    @stubs.annotated_data(
        ('found', ['1.2.3.4']),
        ('not-found', ['4.3.2.1']),
    )
    def test_get_host_ip_addr(self, tag, return_value, mi):
        mi.return_value = return_value
        self.assertEqual('1.2.3.4', self.connection.get_host_ip_addr())

    @mock.patch('socket.gethostname', mock.Mock(return_value='fake_hostname'))
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
                           'Thread(s) per core:  4\n'
                           '\n',
                           None)
        meminfo = mock.MagicMock()
        meminfo.__enter__.return_value = six.moves.cStringIO(
            'MemTotal: 10240000 kB\n'
            'MemFree:   2000000 kB\n'
            'Buffers:     24000 kB\n'
            'Cached:      24000 kB\n')

        mo.side_effect = [
            six.moves.cStringIO('flags: fake flag goes here\n'
                                'processor: 2\n'
                                '\n'),
            meminfo,
        ]
        value = self.connection.get_available_resource(None)
        value['cpu_info'] = json.loads(value['cpu_info'])
        value['supported_instances'] = [[arch.I686, hv_type.LXD,
                                         vm_mode.EXE],
                                        [arch.X86_64, hv_type.LXD,
                                         vm_mode.EXE],
                                        [arch.I686, hv_type.LXC,
                                         vm_mode.EXE],
                                        [arch.X86_64, hv_type.LXC,
                                         vm_mode.EXE]]
        expected = {'cpu_info': {u'arch': platform.uname()[5],
                                 u'features': u'fake flag goes here',
                                 u'model': u'Fake CPU',
                                 u'topology': {u'cores': u'5',
                                               u'sockets': u'10',
                                               u'threads': u'4'},
                                 u'vendor': u'FakeVendor'},
                    'hypervisor_hostname': 'fake_hostname',
                    'hypervisor_type': 'lxd',
                    'hypervisor_version': '011',
                    'local_gb': 1000,
                    'local_gb_used': 500,
                    'memory_mb': 10000,
                    'memory_mb_used': 8000,
                    'numa_topology': None,
                    'supported_instances': [[arch.I686, hv_type.LXD,
                                             vm_mode.EXE],
                                            [arch.X86_64, hv_type.LXD,
                                             vm_mode.EXE],
                                            [arch.I686, hv_type.LXC,
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

    def test_container_reboot(self):
        instance = stubs._fake_instance()
        context = mock.Mock()
        network_info = mock.Mock()
        reboot_type = 'SOFT'
        with test.nested(
                mock.patch.object(self.connection.container_ops,
                                  'reboot')
        ) as (
                reboot
        ):
            self.connection.reboot(context, instance,
                                   network_info, reboot_type)
            self.assertTrue(reboot)

    def test_container_power_off(self):
        instance = stubs._fake_instance()
        with test.nested(
                mock.patch.object(self.connection.container_ops,
                                  'power_off')
        ) as (
                power_off
        ):
            self.connection.power_off(instance)
            self.assertTrue(power_off)

    def test_container_power_on(self):
        context = mock.Mock()
        instance = stubs._fake_instance()
        network_info = mock.Mock()
        with test.nested(
                mock.patch.object(self.connection.container_ops,
                                  'power_on')
        ) as (
                power_on
        ):
            self.connection.power_on(context, instance, network_info)
            self.assertTrue(power_on)

    @stubs.annotated_data(
        ('refresh_security_group_rules', (mock.Mock(),)),
        ('refresh_security_group_members', (mock.Mock(),)),
        ('refresh_provider_fw_rules',),
        ('refresh_instance_security_rules', (mock.Mock(),)),
        ('ensure_filtering_rules_for_instance', (mock.Mock(), mock.Mock())),
        ('filter_defer_apply_on',),
        ('filter_defer_apply_off',),
        ('unfilter_instance', (mock.Mock(), mock.Mock())),
    )
    def test_firewall_calls(self, name, args=()):
        with mock.patch.object(self.connection.container_firewall,
                               'firewall_driver') as mf:
            driver_method = getattr(self.connection, name)
            firewall_method = getattr(mf, name)
            self.assertEqual(
                firewall_method.return_value,
                driver_method(*args))
            firewall_method.assert_called_once_with(*args)

    @mock.patch.object(host.utils, 'execute')
    def test_get_host_uptime(self, me):
        me.return_value = ('out', 'err')
        self.assertEqual('out',
                         self.connection.get_host_uptime())

    @mock.patch('socket.gethostname', mock.Mock(return_value='mock_hostname'))
    def test_get_available_nodes(self):
        self.assertEqual(
            ['mock_hostname'], self.connection.get_available_nodes())

    @mock.patch('socket.gethostname', mock.Mock(return_value='mock_hostname'))
    @stubs.annotated_data(
        ('mock_hostname', True),
        ('wrong_hostname', False),
    )
    def test_node_is_available(self, nodename, available):
        self.assertEqual(available,
                         self.connection.node_is_available(nodename))


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
        'soft_delete',
        'post_live_migration_at_source',
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
        'check_instance_shared_storage_cleanup',
        'manage_image_cache',
    )
    def test_pass(self, method):
        call = getattr(self.connection, method)
        argspec = inspect.getargspec(call)
        self.assertEqual(
            None,
            call(*([None] * (len(argspec.args) - 1))))

    @stubs.annotated_data(
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
