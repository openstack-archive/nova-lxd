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
import ddt
import mock
from nova import test
from nova.virt import fake

from nova.virt.lxd import driver
from nova.virt.lxd import utils as container_dir
import stubs


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
