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
from nova import test
from nova.tests.unit import fake_instance
from nova.tests.unit import fake_network
from nova.virt import fake

from nova.virt.lxd import migrate
from nova.virt.lxd import session

CONF = nova.conf.CONF


class LXDTestContainerMigrate(test.NoDBTestCase):

    def setUp(self):
        super(LXDTestContainerMigrate, self).setUp()

        self.migrate = migrate.LXDContainerMigrate(
            fake.FakeVirtAPI())
        self.context = 'fake_context'
        self.migrate.session = mock.MagicMock()
        self.migrate.config = mock.MagicMock()
        self.migrate.operations = mock.MagicMock()

    @mock.patch.object(session.LXDAPISession, 'container_defined')
    def test_migrate_disk_and_power_off_different_host(
            self, mock_container_defined):
        mock_instance = fake_instance.fake_instance_obj(self.context)
        self.migrate.migrate_disk_and_power_off(
            mock.sentinel.context, mock_instance,
            mock.sentinel.dest, mock.sentinel.flavor,
            mock.sentinel.network_info,
            mock.sentinel.block_device_info,
            mock.sentinel.timeout, mock.sentinel.retry_interval)
        mock_container_defined.return_value = True
        self.migrate.session.container_stop.assert_called_once_with(
            mock_instance.name, mock_instance
        )

    @mock.patch.object(session.LXDAPISession, 'container_defined')
    def test_confirm_migration(self, mock_contaienr_defined):
        mock_instance = fake_instance.fake_instance_obj(self.context)
        fake_network_info = fake_network.fake_get_instance_nw_info
        self.migrate.confirm_migration(
            mock.sentinel.migration, mock_instance, fake_network_info)
        self.migrate.session.profile_delete.assert_called_once_with(
            mock_instance
        )
        self.migrate.session.container_destroy.assert_called_once_with(
            mock_instance.name, mock_instance
        )
        self.migrate.operations.unplug_vifs.assert_called_once_with(
            mock_instance, fake_network_info
        )


class LXDTestLiveMigrate(test.NoDBTestCase):

    def setUp(self):
        super(LXDTestLiveMigrate, self).setUp()

        self.migrate = migrate.LXDContainerMigrate(
            fake.FakeVirtAPI())
        self.context = 'fake_context'
        self.migrate = migrate.LXDContainerMigrate(
            fake.FakeVirtAPI())
        self.migrate.session = mock.MagicMock()
        self.migrate.config = mock.MagicMock()
        self.migrate.operations = mock.MagicMock()

    def test_copy_container_profile(self):
        mock_instance = fake_instance.fake_instance_obj(self.context)
        fake_network_info = fake_network.fake_get_instance_nw_info

        self.migrate._copy_container_profile(
            mock_instance, fake_network_info)
        self.migrate.config.create_profile.assert_called_once_with(
            mock_instance, fake_network_info)
        self.migrate.session.profile_create.assert_called_once_with(
            mock.call.create_proile, mock_instance)

    @mock.patch.object(migrate.LXDContainerMigrate, '_copy_container_profile')
    def test_pre_live_migration(self, mock_container_profile):
        self.migrate.pre_live_migration(
            mock.sentinel.context, mock.sentinel.instance,
            mock.sentinel.block_device_info,
            mock.sentinel.network_info,
            mock.sentinel.disk_info,
            mock.sentinel.migrate_data)

        mock_container_profile.assert_called_once_with(
            mock.sentinel.instance, mock.sentinel.network_info)

    @mock.patch.object(migrate.LXDContainerMigrate, '_container_init')
    def test_live_migration(self, mock_container_init):
        self.flags(my_ip='fakeip')
        mock_post_method = mock.MagicMock()
        self.migrate.live_migration(
            mock.sentinel.context, mock.sentinel.instance,
            mock.sentinel.dest, mock_post_method,
            mock.sentinel.recover_method, mock.sentinel.block_migration,
            mock.sentinel.migrate_data)
        mock_container_init.assert_called_once_with(CONF.my_ip,
                                                    mock.sentinel.instance)
        mock_post_method.assert_called_once_with(
            mock.sentinel.context, mock.sentinel.instance, mock.sentinel.dest,
            mock.sentinel.block_migration, host=mock.sentinel.dest)

    def test_post_live_migration(self):
        mock_instance = fake_instance.fake_instance_obj(self.context)
        self.migrate.post_live_migration(
            mock.sentinel.context, mock_instance,
            mock.sentinel.block_device_info, mock.sentinel.migrate_data)
        self.migrate.session.container_destroy.assert_called_once_with(
            mock_instance.name, mock_instance)
