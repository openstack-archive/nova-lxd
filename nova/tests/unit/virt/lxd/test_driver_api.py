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
import os

import ddt
import mock

from oslo_config import cfg

from nova import test
from nova.virt import fake

from nova.virt.lxd import driver
from nova.virt.lxd import utils as container_dir
import stubs


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

    def test_capabilities(self):
        self.assertFalse(self.connection.capabilities['has_imagecache'])
        self.assertFalse(self.connection.capabilities['supports_recreate'])
        self.assertFalse(
            self.connection.capabilities['supports_migrate_to_same_host'])
        self.assertTrue(
            self.connection.capabilities['supports_attach_interface'])

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
        self.driver.cleanup_live_migration_destination_check(
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
