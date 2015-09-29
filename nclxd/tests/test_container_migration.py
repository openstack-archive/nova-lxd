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

import contextlib

import mock

from nova import test
from nova import utils
from nova.virt import fake

from nclxd.nova.virt.lxd import container_client
from nclxd.nova.virt.lxd import container_config
from nclxd.nova.virt.lxd import container_migrate
from nclxd.nova.virt.lxd import container_ops
from nclxd.nova.virt.lxd import container_utils
from nclxd.tests import stubs


@mock.patch.object(container_migrate, 'CONF', stubs.MockConf())
class LXDTestContainerMigrate(test.NoDBTestCase):

    @mock.patch.object(container_migrate, 'CONF', stubs.MockConf())
    def setUp(self):
        super(LXDTestContainerMigrate, self).setUp()

        self.migrate = container_migrate.LXDContainerMigrate(
            fake.FakeVirtAPI())

    def test_migrate_disk_and_power_off(self):
        instance = stubs._fake_instance()
        context = mock.Mock()
        dest = mock.Mock()
        flavor = mock.Mock()
        network_info = mock.Mock()
        container_config = mock.Mock()
        with contextlib.nested(
            mock.patch.object(container_utils.LXDContainerUtils,
                              'container_stop'),
            mock.patch.object(container_utils.LXDContainerUtils,
                              'container_migrate'),
            mock.patch.object(container_config.LXDContainerConfig,
                              'get_container_config'),
            mock.patch.object(container_client.LXDContainerClient,
                              'container_config'),
            mock.patch.object(container_config.LXDContainerConfig,
                              'configure_container_migrate'),
            mock.patch.object(container_utils.LXDContainerUtils,
                              'container_init'),
            mock.patch.object(utils, 'spawn')
        ) as (
            container_stop,
            container_migrate,
            container_migrate_config,
            get_container_config,
            container_config,
            container_init,
            spawn
        ):
            self.assertEqual({},
                             self.migrate.migrate_disk_and_power_off(
                context, instance, dest, flavor, network_info))
            container_stop.assert_called_once_with(
                instance.uuid, instance.host)

    def test_confirm_migration(self):
        instance = stubs._fake_instance()
        migration = mock.Mock()
        network_info = mock.Mock()
        migration = {'source_compute': 'fake-source',
                     'dest_compute': 'fake-dest'}
        src = migration['source_compute']
        with contextlib.nested(
            mock.patch.object(container_client.LXDContainerClient,
                              'client'),
            mock.patch.object(container_utils.LXDContainerUtils,
                              'container_destroy')
        ) as (
            container_defined,
            container_destroy
        ):
            self.assertEqual(None,
                             (self.migrate.confirm_migration(migration,
                                                             instance,
                                                             network_info)))
            container_destroy.assert_called_once_with(instance.uuid,
                                                      src)

    def test_finish_migration(self):
        context = mock.Mock()
        migration = {'source_compute': 'fake-source',
                     'dest_compute': 'fake-dest'}
        instance = stubs._fake_instance()
        bdevice_info = mock.Mock()
        disk_info = mock.Mock()
        network_info = mock.Mock()
        with contextlib.nested(
            mock.patch.object(container_config.LXDContainerConfig,
                              'get_container_config'),
            mock.patch.object(container_client.LXDContainerClient,
                              'client'),
            mock.patch.object(container_ops.LXDContainerOperations,
                              'start_container')
        ) as (
            get_container_config,
            container_mock_client,
            container_start
        ):
            self.assertEqual(None,
                             (self.migrate.finish_migration(context,
                                                            migration,
                                                            instance,
                                                            disk_info,
                                                            network_info,
                                                            bdevice_info)))
