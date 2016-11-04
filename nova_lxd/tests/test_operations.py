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

from nova_lxd.nova.virt.lxd import config
from nova_lxd.nova.virt.lxd import image
from nova_lxd.nova.virt.lxd import operations as container_ops
from nova_lxd.nova.virt.lxd import session
from nova_lxd.tests import stubs


@ddt.ddt
@mock.patch.object(container_ops, 'CONF', stubs.MockConf())
class LXDTestContainerOps(test.NoDBTestCase):
    """LXD Container operations unit tests."""

    def setUp(self):
        super(LXDTestContainerOps, self).setUp()
        self.ml = stubs.lxd_mock()
        lxd_patcher = mock.patch('pylxd.api.API',
                                 mock.Mock(return_value=self.ml))
        lxd_patcher.start()
        self.addCleanup(lxd_patcher.stop)

        self.operations = (
            container_ops.LXDContainerOperations(fake.FakeVirtAPI()))
        self.mv = mock.MagicMock()
        vif_patcher = mock.patch.object(self.operations,
                                        'vif_driver',
                                        self.mv)
        vif_patcher.start()
        self.addCleanup(vif_patcher.stop)

    @mock.patch('oslo_utils.fileutils.ensure_tree')
    def test_spawn_container(self, mock_ensure_tree):
        """Test spawn method. Ensure that the right calls
           are made when creating a container.
        """
        context = mock.Mock()
        instance = stubs._fake_instance()
        image_meta = mock.Mock()
        injected_files = mock.Mock()
        admin_password = mock.Mock()
        network_info = mock.Mock()
        block_device_info = mock.Mock()

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
                                                   block_device_info))

    def test_reboot_container(self):
        """Test the reboot method. Ensure that the proper
           calls are made when rebooting a continer.
        """
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
        """Test the destroy conainer method. Ensure that
           the correct calls are made when removing
           the contianer.
        """
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
        """Test the power_off method. Ensure that the proper
           calls are made when the container is powered
           off.
        """
        instance = stubs._fake_instance()
        with test.nested(
            mock.patch.object(session.LXDAPISession, 'container_stop')
        ) as (mock_container_stop):
            self.assertEqual(None,
                             self.operations.power_off(instance))
            self.assertTrue(mock_container_stop)

    def test_power_on(self):
        """test the power_on method. Ensure that the proper
           calls are made when the container is powered on.
        """
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
        """Test the pause container method. Ensure that that
           the proper calls are made when pausing the container.
        """
        instance = stubs._fake_instance()
        with test.nested(
            mock.patch.object(session.LXDAPISession, 'container_pause')
        ) as (mock_container_pause):
            self.assertEqual(None,
                             self.operations.pause(instance))
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

    @mock.patch.object(image.LXDContainerImage, 'setup_image')
    def test_fetch_image(self, mock_fetch_image):
        instance = stubs._fake_instance()
        context = mock.Mock()
        self.operations._fetch_image(context, instance, {})
        mock_fetch_image.assert_called_once_with(context, instance, {})

    @mock.patch.object(container_ops.LXDContainerOperations, 'plug_vifs')
    def test_setup_network(self, mock_plug_vifs):
        instance = stubs._fake_instance()

        self.operations._setup_network(instance.name, [], instance)
        mock_plug_vifs.assert_called_once_with([], instance)

    @mock.patch.object(session.LXDAPISession, 'profile_create')
    @mock.patch.object(config.LXDContainerConfig, 'create_profile')
    def test_setup_profile(self, mock_profile_create, mock_create_profile):
        instance = stubs._fake_instance()
        network_info = mock.Mock()
        container_profile = mock.Mock()
        self.operations._setup_profile(instance.name, instance, network_info)
        mock_profile_create.assert_has_calls(
            [mock.call(instance, network_info)])
        container_profile = mock_profile_create.return_value
        mock_create_profile.assert_has_calls(
            [mock.call(container_profile, instance)])

    @mock.patch.object(config.LXDContainerConfig, 'create_container')
    @mock.patch.object(session.LXDAPISession, 'container_init')
    @mock.patch.object(session.LXDAPISession, 'container_start')
    def test_setup_container(self, mock_create_container, mock_container_init,
                             mock_container_start):
        instance = stubs._fake_instance()
        self.assertEqual(None,
                         self.operations._setup_container(instance.name,
                                                          instance))
