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

from nova import test
from nova.virt import fake

from oslo_config import cfg

from nova_lxd.nova.virt.lxd import config
from nova_lxd.nova.virt.lxd import migrate
from nova_lxd.nova.virt.lxd import operations
from nova_lxd.nova.virt.lxd import session
from nova_lxd.tests import stubs

CONF = cfg.CONF
CONF.import_opt('my_ip', 'nova.netconf')


class LXDTestContainerMigrate(test.NoDBTestCase):

    def setUp(self):
        super(LXDTestContainerMigrate, self).setUp()

        self.migrate = migrate.LXDContainerMigrate(
            fake.FakeVirtAPI())

    def test_migrate_disk_power_off_resize(self):
        self.flags(my_ip='fakeip')
        instance = stubs._fake_instance()
        network_info = mock.Mock()
        flavor = mock.Mock()
        context = mock.Mock()
        dest = 'fakeip'

        with test.nested(
            mock.patch.object(session.LXDAPISession, 'container_defined'),
            mock.patch.object(config.LXDContainerConfig, 'create_profile'),
            mock.patch.object(session.LXDAPISession, 'profile_update')
        ) as (
            mock_container_defined,
            mock_create_profile,
            mock_profile_update
        ):
            self.assertEqual('',
                             self.migrate.migrate_disk_and_power_off(
                                 context, instance, dest, flavor,
                                 network_info))
            mock_container_defined.assert_called_once_with(instance.name,
                                                           instance)
            mock_create_profile.assert_called_once_with(instance,
                                                        network_info)

    def test_confirm_migration(self):
        migration = mock.Mock()
        instance = stubs._fake_instance()
        network_info = mock.Mock()

        with test.nested(
            mock.patch.object(session.LXDAPISession, 'container_defined'),
            mock.patch.object(session.LXDAPISession, 'profile_delete'),
            mock.patch.object(session.LXDAPISession, 'container_destroy'),
            mock.patch.object(operations.LXDContainerOperations,
                              'unplug_vifs'),
        ) as (
                mock_container_defined,
                mock_profile_delete,
                mock_container_destroy,
                mock_unplug_vifs):
            self.assertEqual(None,
                             self.migrate.confirm_migration(migration,
                                                            instance,
                                                            network_info))
            mock_container_defined.assert_called_once_with(instance.name,
                                                           instance)
            mock_profile_delete.assert_called_once_with(instance)
            mock_unplug_vifs.assert_called_once_with(instance,
                                                     network_info)
