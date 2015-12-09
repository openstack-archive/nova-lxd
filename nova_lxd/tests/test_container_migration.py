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

from nova_lxd.nova.virt.lxd import container_config
from nova_lxd.nova.virt.lxd import container_migrate
from nova_lxd.nova.virt.lxd import container_ops
from nova_lxd.nova.virt.lxd.session import session
from nova_lxd.tests import stubs


@mock.patch.object(container_migrate, 'CONF', stubs.MockConf())
@mock.patch.object(session, 'CONF', stubs.MockConf())
class LXDTestContainerMigrate(test.NoDBTestCase):

    @mock.patch.object(container_migrate, 'CONF', stubs.MockConf())
    @mock.patch.object(session, 'CONF', stubs.MockConf())
    def setUp(self):
        super(LXDTestContainerMigrate, self).setUp()

        self.migrate = container_migrate.LXDContainerMigrate(
            fake.FakeVirtAPI())

    @mock.patch.object(session.LXDAPISession, 'container_migrate')
    def test_finish_migration(self, mo):
        context = mock.Mock()
        migration = {'source_compute': 'fake-source',
                     'dest_compute': 'fake-dest'}
        instance = stubs._fake_instance()
        bdevice_info = mock.Mock()
        disk_info = mock.Mock()
        network_info = mock.Mock()
        with test.nested(
            mock.patch.object(session.LXDAPISession,
                              'container_defined'),
            mock.patch.object(session.LXDAPISession,
                              'container_stop'),
            mock.patch.object(container_config.LXDContainerConfig,
                              'configure_container_migrate'),
            mock.patch.object(session.LXDAPISession,
                              'container_init'),
            mock.patch.object(container_ops.LXDContainerOperations,
                              'start_container'),
        ) as (
            container_defined,
            container_stop,
            container_migrate,
            container_init,
            container_start
        ):
            def side_effect(*args, **kwargs):
                # XXX: rockstar (7 Dec 2015) - This mock is a little greedy,
                # and hits too many interfaces. It should become more specific
                # to the single places it needs to fully mocked. Truthiness of
                # the mock changes in py3.
                if args[0] == 'defined':
                    return False
            container_defined.side_effect = side_effect
            self.assertEqual(None,
                             (self.migrate.finish_migration(context,
                                                            migration,
                                                            instance,
                                                            disk_info,
                                                            network_info,
                                                            bdevice_info)))
