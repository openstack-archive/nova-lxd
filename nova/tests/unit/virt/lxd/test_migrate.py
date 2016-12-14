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

import mock

import nova.conf
from nova import exception
from nova import test
from pylxd.deprecated import exceptions as lxd_exceptions

from nova.virt.lxd import driver

CONF = nova.conf.CONF


class LXDTestLiveMigrate(test.NoDBTestCase):

    def setUp(self):
        super(LXDTestLiveMigrate, self).setUp()

        self.driver = driver.LXDDriver(None)
        self.context = 'fake_context'
        self.driver.session = mock.MagicMock()
        self.driver.config = mock.MagicMock()
        self.driver.operations = mock.MagicMock()

    @mock.patch.object(driver.LXDDriver, '_migrate')
    def test_live_migration(self, mock_migrate):
        """Verify that the correct live migration calls
           are made.
        """
        self.flags(my_ip='fakeip')
        mock_post_method = mock.MagicMock()
        self.driver.live_migration(
            mock.sentinel.context, mock.sentinel.instance,
            mock.sentinel.dest, mock_post_method,
            mock.sentinel.recover_method, mock.sentinel.block_migration,
            mock.sentinel.migrate_data)
        mock_migrate.assert_called_once_with(mock.sentinel.dest,
                                             mock.sentinel.instance)
        mock_post_method.assert_called_once_with(
            mock.sentinel.context, mock.sentinel.instance, mock.sentinel.dest,
            mock.sentinel.block_migration)

    @mock.patch.object(driver.LXDDriver, '_migrate')
    def test_live_migration_failed(self, mock_migrate):
        """Verify that an exception is raised when live-migration
           fails.
        """
        self.flags(my_ip='fakeip')
        mock_migrate.side_effect = \
            lxd_exceptions.APIError(500, 'Fake')
        self.assertRaises(
            lxd_exceptions.APIError,
            self.driver.live_migration, mock.sentinel.context,
            mock.sentinel.instance, mock.sentinel.dest,
            mock.sentinel.recover_method, mock.sentinel.block_migration,
            mock.sentinel.migrate_data)

    def test_live_migration_not_allowed(self):
        """Verify an exception is raised when live migration is not allowed."""
        self.flags(allow_live_migration=False,
                   group='lxd')
        self.assertRaises(exception.MigrationPreCheckError,
                          self.driver.check_can_live_migrate_source,
                          mock.sentinel.context, mock.sentinel.instance,
                          mock.sentinel.dest_check_data,
                          mock.sentinel.block_device_info)

    def test_live_migration_allowed(self):
        """Verify live-migration is allowed when the allow_lvie_migrate
           flag is True.
        """
        self.flags(allow_live_migration=True,
                   group='lxd')
        self.assertEqual(mock.sentinel.dest_check_data,
                         self.driver.check_can_live_migrate_source(
                             mock.sentinel.context, mock.sentinel.instance,
                             mock.sentinel.dest_check_data,
                             mock.sentinel.block_device_info))
