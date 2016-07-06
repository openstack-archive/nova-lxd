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
import collections
import inspect
import json
import os
import platform
from pylxd import exceptions as lxdcore_exceptions

import ddt
import mock
import six

from oslo_config import cfg

from nova.compute import arch
from nova.compute import hv_type
from nova.compute import power_state
from nova.compute import vm_mode
from nova import exception
from nova import test
from nova.virt import fake
from nova.virt import hardware

from nova.virt.lxd import driver
from nova.virt.lxd import session
from nova.virt.lxd import utils as container_dir
import stubs

MockContainer = collections.namedtuple('Container', ['name'])


class LXDTestConfig(test.NoDBTestCase):

    def test_config(self):
        self.assertIsInstance(driver.CONF.lxd, cfg.ConfigOpts.GroupAttr)
        self.assertEqual(os.path.abspath('/var/lib/lxd'),
                         os.path.abspath(driver.CONF.lxd.root_dir))
        self.assertEqual(-1, driver.CONF.lxd.timeout)


@ddt.ddt
@mock.patch.object(container_dir, 'CONF', stubs.MockConf())
@mock.patch.object(driver, 'CONF', stubs.MockConf())
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

        self.driver = driver.LXDDriver(mock.MagicMock())
        self.driver.container_migrate = mock.MagicMock()

        mock_client = mock.Mock()
        mock_client.containers.all.return_value = [
            MockContainer('mock-instance-1'),
            MockContainer('mock-instance-2'),
        ]
        self.connection.client = mock_client

    def test_capabilities(self):
        self.assertFalse(self.connection.capabilities['has_imagecache'])
        self.assertFalse(self.connection.capabilities['supports_recreate'])
        self.assertFalse(
            self.connection.capabilities['supports_migrate_to_same_host'])
        self.assertTrue(
            self.connection.capabilities['supports_attach_interface'])

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
        mock_response = mock.Mock()
        mock_response.json.return_value = {
            'error': 'Fake',
        }

        self.connection.client.containers.all.side_effect = (
            lxdcore_exceptions.LXDAPIException(mock_response))
        self.assertRaises(
            exception.NovaException,
            self.connection.list_instances
        )

    @mock.patch('nova.virt.configdrive.required_by')
    def test_spawn(self, mock_configdrive):
        """Test spawn method. Ensure that the right calls
           are made when creating a container.
        """
        context = mock.Mock()
        instance = stubs._fake_instance()
        instance_name = instance.name
        image_meta = mock.Mock()
        injected_files = mock.Mock()
        admin_password = mock.Mock()
        network_info = mock.Mock()
        block_device_info = mock.Mock()

        with test.nested(
            mock.patch.object(session.LXDAPISession, 'container_defined'),
            mock.patch('os.path.exists'),
            mock.patch('oslo_utils.fileutils.ensure_tree'),
            mock.patch.object(
                self.connection, 'setup_image'),
            mock.patch.object(self.connection, 'plug_vifs'),
            mock.patch.object(self.connection, 'create_profile'),
            mock.patch.object(session.LXDAPISession, 'profile_create'),
            mock.patch.object(session.LXDAPISession, 'container_init'),
            mock.patch.object(session.LXDAPISession, 'container_start')

        ) as (
            mock_container_defined,
            mock_path_exists,
            mock_ensure_tree,
            mock_setup_image,
            mock_plug_vif,
            mock_container_profile,
            mock_profile_create,
            mock_container_init,
            mock_container_start
        ):
            mock_container_defined.return_value = False
            mock_path_exists.return_value = False
            mock_configdrive.return_value = False
            mock_container_profile.return_value = {}

            container_config = {'devices': {},
                                'name': 'instance-00000001',
                                'profiles': ['instance-00000001'],
                                'source': {'alias': 'fake_image',
                                           'type': 'image'}}

            self.assertEqual(None,
                             self.connection.spawn(context, instance,
                                                   image_meta,
                                                   injected_files,
                                                   admin_password,
                                                   network_info,
                                                   block_device_info))
            mock_container_defined.assert_called_once_with(
                instance_name, instance)
            mock_path_exists.assert_called_once_with(
                '/fake/instances/path/%s' % instance.name)
            mock_setup_image.assert_called_once_with(
                context, instance, image_meta)
            mock_plug_vif.assert_called_once_with(instance, network_info)
            mock_container_profile.assert_called_once_with(
                instance, network_info, block_device_info)
            mock_profile_create.assert_called_once_with({}, instance)
            mock_container_init.assert_called_once_with(container_config,
                                                        instance)
            mock_container_start.assert_called_once_with(
                instance_name, instance)

    @mock.patch('nova.virt.configdrive.required_by')
    def test_spawn_with_configdrive(self, mock_configdrive):
        """Test spawn method. Ensure that the right calls
           are made when creating a container with a configdrive
        """
        context = mock.Mock()
        instance = stubs._fake_instance()
        instance_name = instance.name
        image_meta = mock.Mock()
        injected_files = mock.Mock()
        admin_password = mock.Mock()
        network_info = mock.Mock()
        block_device_info = mock.Mock()

        with test.nested(
                mock.patch.object(session.LXDAPISession, 'container_defined'),
                mock.patch('os.path.exists'),
                mock.patch('oslo_utils.fileutils.ensure_tree'),
                mock.patch.object(
                    self.connection, 'setup_image'),
                mock.patch.object(self.connection, 'plug_vifs'),
                mock.patch.object(self.connection, 'create_profile'),
                mock.patch.object(session.LXDAPISession, 'profile_create'),
                mock.patch.object(self.connection, '_add_configdrive'),
                mock.patch.object(session.LXDAPISession, 'container_init'),
                mock.patch.object(session.LXDAPISession, 'container_start')

        ) as (
                mock_container_defined,
                mock_path_exists,
                mock_ensure_tree,
                mock_setup_image,
                mock_plug_vif,
                mock_container_profile,
                mock_profile_create,
                mock_add_configdrive,
                mock_container_init,
                mock_container_start
        ):
            mock_container_defined.return_value = False
            mock_path_exists.return_value = False
            mock_configdrive.return_value = True
            mock_container_profile.return_value = {}

            container_config = {'devices': {},
                                'name': 'instance-00000001',
                                'profiles': ['instance-00000001'],
                                'source': {'alias': 'fake_image',
                                           'type': 'image'}}

            self.assertEqual(None,
                             self.connection.spawn(context, instance,
                                                   image_meta,
                                                   injected_files,
                                                   admin_password,
                                                   network_info,
                                                   block_device_info))
            mock_container_defined.assert_called_once_with(
                instance_name, instance)
            mock_path_exists.assert_called_once_with(
                '/fake/instances/path/%s' % instance.name)
            mock_setup_image.assert_called_once_with(
                context, instance, image_meta)
            mock_plug_vif.assert_called_once_with(instance, network_info)
            mock_container_profile.assert_called_once_with(
                instance, network_info, block_device_info)
            mock_profile_create.assert_called_once_with({}, instance)
            mock_configdrive.assert_called_once_with(instance)
            mock_add_configdrive.assert_called_once_with(
                instance, injected_files)
            mock_container_init.assert_called_once_with(container_config,
                                                        instance)
            mock_container_start.assert_called_once_with(
                instance_name, instance)

    def test_destroy(self):
        instance = stubs._fake_instance()
        context = mock.Mock()
        network_info = mock.Mock()
        with test.nested(
                mock.patch.object(session.LXDAPISession,
                                  'profile_delete'),
                mock.patch.object(session.LXDAPISession,
                                  'container_destroy'),
                mock.patch.object(self.connection,
                                  'cleanup'),
        ) as (
            mock_profile_delete,
            mock_container_destroy,
            mock_container_cleanup
        ):
            self.assertEqual(None,
                             self.connection.destroy(context, instance,
                                                     network_info))
            mock_profile_delete.assert_called_once_with(instance)
            mock_container_destroy.assert_called_once_with(instance.name,
                                                           instance)
            mock_container_cleanup.assert_called_once_with(context, instance,
                                                           network_info, None)

    @mock.patch('os.path.exists', mock.Mock(return_value=True))
    @mock.patch('shutil.rmtree')
    @mock.patch('pwd.getpwuid', mock.Mock(return_value=mock.Mock(pw_uid=1234)))
    @mock.patch.object(driver.utils, 'execute')
    def test_cleanup(self, mr, mu):
        instance = stubs.MockInstance()
        block_device_info = mock.Mock()
        self.assertEqual(
            None,
            self.connection.cleanup({}, instance, [], block_device_info, None, None, None))

    @mock.patch('six.moves.builtins.open')
    @mock.patch.object(driver.utils, 'execute')
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

    @mock.patch.object(driver.compute_utils, 'get_machine_ips')
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
    @mock.patch.object(driver.utils, 'execute')
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

    @mock.patch.object(session.LXDAPISession, 'container_reboot')
    def test_container_reboot(self, mock_container_reboot):
        """Verify reboot method calls are correct."""
        instance = stubs._fake_instance()
        context = mock.Mock()
        network_info = mock.Mock()
        reboot_type = 'SOFT'
        self.connection.reboot(context, instance,
                               network_info, reboot_type)
        mock_container_reboot.assert_called_once_with(instance)

    def test_container_power_off(self):
        instance = stubs._fake_instance()
        with test.nested(
            mock.patch.object(session.LXDAPISession, 'container_stop')
        ) as (mock_container_stop):
            self.assertEqual(None,
                             self.connection.power_off(instance))
            self.assertTrue(mock_container_stop)

    def test_container_power_on(self):
        context = mock.Mock()
        instance = stubs._fake_instance()
        network_info = mock.Mock()
        block_device_info = mock.Mock()
        with test.nested(
            mock.patch.object(session.LXDAPISession, 'container_start')
        ) as (mock_container_start):
            self.assertEqual(None,
                             self.connection.power_on(context, instance,
                                                      network_info,
                                                      block_device_info))
            self.assertTrue(mock_container_start)

    def test_pause_container(self):
        """Test the pause container method. Ensure that that
           the proper calls are made when pausing the container.
        """
        instance = stubs._fake_instance()
        with test.nested(
            mock.patch.object(session.LXDAPISession, 'container_pause')
        ) as (mock_container_pause):
            self.assertEqual(None,
                             self.connection.pause(instance))
            self.assertTrue(mock_container_pause)

    def test_unpause_container(self):
        """Test the unapuse continaer. Ensure that the proper
           calls are made when unpausing a container.
        """
        instance = stubs._fake_instance()
        with test.nested(
            mock.patch.object(session.LXDAPISession, 'container_unpause')
        ) as (mock_container_unpause):
            self.assertEqual(None,
                             self.connection.unpause(instance))
            self.assertTrue(mock_container_unpause)

    def test_container_suspend(self):
        instance = stubs._fake_instance()
        context = mock.Mock()
        with test.nested(
            mock.patch.object(session.LXDAPISession, 'container_pause')
        ) as (mock_container_suspend):
            self.assertEqual(None,
                             self.connection.suspend(context, instance))
            self.assertTrue(mock_container_suspend)

    def test_container_resume(self):
        instance = stubs._fake_instance()
        context = mock.Mock()
        network_info = mock.Mock()
        with test.nested(
            mock.patch.object(session.LXDAPISession, 'container_unpause')
        ) as (mock_container_resume):
            self.assertEqual(None,
                             self.connection.resume(context, instance,
                                                    network_info))
            self.assertTrue(mock_container_resume)

    @stubs.annotated_data(
        ('refresh_instance_security_rules', (mock.Mock(),)),
        ('ensure_filtering_rules_for_instance', (mock.Mock(), mock.Mock())),
        ('filter_defer_apply_on',),
        ('filter_defer_apply_off',),
        ('unfilter_instance', (mock.Mock(), mock.Mock())),
    )
    def test_firewall_calls(self, name, args=()):
        with mock.patch.object(self.connection,
                               'firewall_driver') as mf:
            driver_method = getattr(self.connection, name)
            firewall_method = getattr(mf, name)
            self.assertEqual(
                firewall_method.return_value,
                driver_method(*args))
            firewall_method.assert_called_once_with(*args)

    @mock.patch.object(driver.utils, 'execute')
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

    def test_pre_live_migration(self):
        """Verify the pre_live_migration call."""
        self.driver.pre_live_migration(
            mock.sentinel.context, mock.sentinel.instance,
            mock.sentinel.block_device_info,
            mock.sentinel.network_info,
            mock.sentinel.disk_info,
            mock.sentinel.migrate_data)
        self.driver.container_migrate.pre_live_migration.\
            assert_called_once_with(
                mock.sentinel.context, mock.sentinel.instance,
                mock.sentinel.block_device_info,
                mock.sentinel.network_info,
                mock.sentinel.disk_info,
                mock.sentinel.migrate_data)

    def test_live_migration(self):
        """Verify the live_migration call."""
        self.driver.live_migration(
            mock.sentinel.context, mock.sentinel.instance,
            mock.sentinel.dest, mock.sentinel.post_method,
            mock.sentinel.recover_method,
            mock.sentinel.block_migration,
            mock.sentinel.migrate_data)
        self.driver.container_migrate.\
            live_migration.assert_called_once_with(
                mock.sentinel.context, mock.sentinel.instance,
                mock.sentinel.dest, mock.sentinel.post_method,
                mock.sentinel.recover_method,
                mock.sentinel.block_migration,
                mock.sentinel.migrate_data)

    def test_post_live_migration(self):
        """Verifty the post_live_migratoion call."""
        self.driver.post_live_migration(
            mock.sentinel.context, mock.sentinel.instance,
            mock.sentinel.block_device_info, mock.sentinel.migrate_data)
        self.driver.container_migrate.post_live_migration.\
            assert_called_once_with(
                mock.sentinel.context, mock.sentinel.instance,
                mock.sentinel.block_device_info,
                mock.sentinel.migrate_data)

    def test_post_live_migration_at_destination(self):
        """Verify the post_live_migration_at_destination call."""
        self.driver.post_live_migration_at_destination(
            mock.sentinel.context, mock.sentinel.instance,
            mock.sentinel.network_info,
            mock.sentinel.block_migration,
            mock.sentinel.block_device_info)
        self.driver.container_migrate.post_live_migration_at_destination.\
            assert_called_once_with(
                mock.sentinel.context, mock.sentinel.instance,
                mock.sentinel.network_info,
                mock.sentinel.block_migration,
                mock.sentinel.block_device_info)

    def test_check_can_live_migrate_destination(self):
        """Verify the check_can_live_migrate_destination call."""
        self.driver.check_can_live_migrate_destination(
            mock.sentinel.context, mock.sentinel.instance,
            mock.sentinel.src_compute_info, mock.sentinel.dst_compute_info,
            mock.sentinel.block_migration, mock.sentinel.disk_over_commit)
        mtd = self.driver.container_migrate.check_can_live_migrate_destination
        mtd.assert_called_once_with(
            mock.sentinel.context, mock.sentinel.instance,
            mock.sentinel.src_compute_info,
            mock.sentinel.dst_compute_info,
            mock.sentinel.block_migration,
            mock.sentinel.disk_over_commit)

    def test_check_can_live_migrate_destination_cleanup(self):
        """Verify the check_can_live_migration destination cleanup call."""
        self.driver.check_can_live_migrate_destination_cleanup(
            mock.sentinel.context, mock.sentinel.instance
        )
        self.driver.container_migrate. \
            check_can_live_migrate_destination_cleanup.assert_called_once_with(
                mock.sentinel.context, mock.sentinel.instance
            )

    def test_check_can_live_migrate_source(self):
        """Verify check_can_live_migrate_source call."""
        self.driver.check_can_live_migrate_source(
            mock.sentinel.context, mock.sentinel.instance,
            mock.sentinel.dest_check_data,
            mock.sentinel.block_device_info
        )
        mtd = self.driver.container_migrate.check_can_live_migrate_source
        mtd.assert_called_once_with(
            mock.sentinel.context, mock.sentinel.instance,
            mock.sentinel.dest_check_data,
            mock.sentinel.block_device_info
        )


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
        'check_instance_shared_storage_local',
        'check_instance_shared_storage_remote',
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
