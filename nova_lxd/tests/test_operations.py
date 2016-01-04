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

from nova_lxd.nova.virt.lxd import operations as container_ops
from nova_lxd.nova.virt.lxd.session import session
from nova_lxd.tests import stubs


@ddt.ddt
@mock.patch.object(container_ops, 'CONF', stubs.MockConf())
class LXDTestContainerOps(test.NoDBTestCase):

    def setUp(self):
        super(LXDTestContainerOps, self).setUp()
        self.ml = stubs.lxd_mock()
        lxd_patcher = mock.patch('pylxd.api.API',
                                 mock.Mock(return_value=self.ml))
        lxd_patcher.start()
        self.addCleanup(lxd_patcher.stop)

        self.operations = (
            container_ops.LXDContainerOperations(fake.FakeVirtAPI()))
        self.mc = mock.MagicMock()
        config_patcher = mock.patch.object(self.operations,
                                           'container_config',
                                           self.mc)
        config_patcher.start()
        self.addCleanup(config_patcher.stop)
        self.mv = mock.MagicMock()
        vif_patcher = mock.patch.object(self.operations,
                                        'vif_driver',
                                        self.mv)
        vif_patcher.start()
        self.addCleanup(vif_patcher.stop)

    def test_spawn(self):
        context = mock.Mock()
        instance = stubs._fake_instance()
        image_meta = mock.Mock()
        injected_files = mock.Mock()
        admin_password = mock.Mock()
        network_info = mock.Mock()
        block_device_info = mock.Mock()
        rescue = False

        with test.nested(
            mock.patch.object(session.LXDAPISession, 'container_defined'),
            mock.patch.object(container_ops.LXDContainerOperations,
                              '_fetch_image'),
            mock.patch.object(container_ops.LXDContainerOperations,
                              '_setup_network'),
            mock.patch.object(container_ops.LXDContainerOperations,
                              '_setup_profile'),
            mock.patch.object(container_ops.LXDContainerOperations,
                              '_add_configdrive'),
            mock.patch.object(container_ops.LXDContainerOperations,
                              '_setup_container')
        ) as (
            mock_container_defined,
            mock_fetch_image,
            mock_setup_network,
            mock_setup_profile,
            mock_add_configdrive,
            mock_setup_container
        ):
            mock_container_defined.return_value = False
            self.assertEqual(None,
                             self.operations.spawn(context, instance,
                                                   image_meta,
                                                   injected_files,
                                                   admin_password,
                                                   network_info,
                                                   block_device_info, rescue))

    def test_reboot_container(self):
        instance = stubs._fake_instance()
        context = mock.Mock()
        with test.nested(
            mock.patch.object(session.LXDAPISession, 'container_reboot')
        ) as (container_reboot):
            self.assertEqual(None,
                             self.operations.reboot(context, instance, {},
                                                    None, None, None))
            self.assertTrue(container_reboot)

    def test_destroy_container(self):
        context = mock.Mock()
        instance = stubs._fake_instance()
        network_info = mock.Mock()

        with test.nested(
            mock.patch.object(session.LXDAPISession, 'profile_delete'),
            mock.patch.object(session.LXDAPISession, 'container_destroy'),
            mock.patch.object(container_ops.LXDContainerOperations, 'cleanup'),
        ) as (
            mock_profile_delete,
            mock_container_destroy,
            mock_cleanup
        ):
            self.assertEqual(None,
                             self.operations.destroy(context,
                                                     instance, network_info))
            self.assertTrue(mock_profile_delete)
            self.assertTrue(mock_container_destroy)

    def test_power_off(self):
        instance = stubs._fake_instance()
        with test.nested(
            mock.patch.object(session.LXDAPISession, 'container_stop')
        ) as (mock_container_stop):
            self.assertEqual(None,
                             self.operations.power_off(instance))
            self.assertTrue(mock_container_stop)

    def test_power_on(self):
        instance = stubs._fake_instance()
        network_info = mock.Mock()
        context = mock.Mock()
        block_device_info = mock.Mock()
        with test.nested(
            mock.patch.object(session.LXDAPISession, 'container_start')
        ) as (mock_container_start):
            self.assertEqual(None,
                             self.operations.power_on(context, instance,
                                                      network_info,
                                                      block_device_info))
            self.assertTrue(mock_container_start)

    def test_pause_container(self):
        instance = stubs._fake_instance()
        with test.nested(
            mock.patch.object(session.LXDAPISession, 'container_pause')
        ) as (mock_container_pause):
            self.assertEqual(None,
                             self.operations.pause(instance))
            self.assertTrue(mock_container_pause)

    def test_unpause_container(self):
        instance = stubs._fake_instance()
        with test.nested(
            mock.patch.object(session.LXDAPISession, 'container_unpause')
        ) as (mock_container_unpause):
            self.assertEqual(None,
                             self.operations.unpause(instance))
            self.assertTrue(mock_container_unpause)

    def test_container_suspend(self):
        instance = stubs._fake_instance()
        context = mock.Mock()
        with test.nested(
            mock.patch.object(session.LXDAPISession, 'container_pause')
        ) as (mock_container_suspend):
            self.assertEqual(None,
                             self.operations.suspend(context, instance))
            self.assertTrue(mock_container_suspend)

    def test_container_resume(self):
        instance = stubs._fake_instance()
        context = mock.Mock()
        network_info = mock.Mock()
        with test.nested(
            mock.patch.object(session.LXDAPISession, 'container_unpause')
        ) as (mock_container_resume):
            self.assertEqual(None,
                             self.operations.resume(context, instance,
                                                    network_info))
            self.assertTrue(mock_container_resume)

    def test_container_rescue(self):
        context = mock.Mock()
        instance = stubs._fake_instance()
        network_info = mock.Mock()
        image_meta = mock.Mock()
        rescue_password = mock.Mock()

        with test.nested(
            mock.patch.object(session.LXDAPISession, 'container_defined'),
            mock.patch.object(session.LXDAPISession, 'container_stop'),
            mock.patch.object(container_ops.LXDContainerOperations,
                              '_container_local_copy'),
            mock.patch.object(session.LXDAPISession, 'container_destroy'),
            mock.patch.object(container_ops.LXDContainerOperations,
                              'spawn'),
        ) as (
            mock_container_defined,
            mock_container_stop,
            mock_container_copy,
            mock_container_destroy,
            mock_spawn
        ):
            self.assertEqual(None,
                             self.operations.rescue(context, instance,
                                                    network_info, image_meta,
                                                    rescue_password))
            mock_container_defined.assert_called_once_with(instance.name,
                                                           instance)

    def test_container_unrescue(self):
        instance = stubs._fake_instance()
        network_info = mock.Mock()

        with test.nested(
            mock.patch.object(session.LXDAPISession, 'container_move'),
            mock.patch.object(session.LXDAPISession, 'container_destroy')
        ) as (
            mock_container_move,
            mock_container_destroy
        ):
            self.assertEqual(None,
                             self.operations.unrescue(instance, network_info))
            mock_container_move.assert_called_once_with(
                'instance-00000001-backup', {'name': 'instance-00000001'},
                instance)
            mock_container_destroy.assert_called_once_with(instance.name,
                                                           instance.host,
                                                           instance)
