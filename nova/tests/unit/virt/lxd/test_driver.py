# Copyright 2016 Canonical Ltd
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

import mock
from nova import context
from nova import exception
from nova import test
from nova.compute import power_state
from nova.tests.unit import fake_instance
from pylxd import exceptions as lxdcore_exceptions

from nova.virt.lxd import driver

MockResponse = collections.namedtuple('Response', ['status_code'])

MockContainer = collections.namedtuple('Container', ['name'])
MockContainerState = collections.namedtuple(
    'ContainerState', ['status_code', 'memory'])


class LXDDriverTest(test.NoDBTestCase):
    """Tests for nova.virt.lxd.driver.LXDDriver."""

    def setUp(self):
        super(LXDDriverTest, self).setUp()

        self.Client_patcher = mock.patch('nova.virt.lxd.driver.pylxd.Client')
        self.Client = self.Client_patcher.start()

        self.client = mock.Mock()
        self.Client.return_value = self.client

        self.CONF_patcher = mock.patch('nova.virt.lxd.driver.CONF')
        self.CONF = self.CONF_patcher.start()
        self.CONF.instances_path = '/path/to/instances'

    def tearDown(self):
        super(LXDDriverTest, self).tearDown()
        self.Client_patcher.stop()
        self.CONF_patcher.stop()

    def test_init_host(self):
        """init_host initializes the pylxd Client."""
        lxd_driver = driver.LXDDriver(None)
        lxd_driver.init_host(None)

        self.Client.assert_called_once_with()
        self.assertEqual(self.client, lxd_driver.client)

    def test_init_host_fail(self):
        def side_effect():
            raise lxdcore_exceptions.ClientConnectionFailed()
        self.Client.side_effect = side_effect
        self.Client.return_value = None

        lxd_driver = driver.LXDDriver(None)

        self.assertRaises(exception.HostNotFound, lxd_driver.init_host, None)

    def test_get_info(self):
        container = mock.Mock()
        container.state.return_value = MockContainerState(
            100, {'usage': 4000, 'usage_peak': 4500})
        self.client.containers.get.return_value = container

        ctx = context.get_admin_context()
        instance = fake_instance.fake_instance_obj(ctx, name='test')
        lxd_driver = driver.LXDDriver(None)
        lxd_driver.init_host(None)

        info = lxd_driver.get_info(instance)

        self.assertEqual(power_state.RUNNING, info.state)
        self.assertEqual(3, info.mem_kb)
        self.assertEqual(4, info.max_mem_kb)
        self.assertEqual(1, info.num_cpu)
        self.assertEqual(0, info.cpu_time_ns)

    def test_list_instances(self):
        self.client.containers.all.return_value = [
            MockContainer('mock-instance-1'),
            MockContainer('mock-instance-2'),
        ]
        lxd_driver = driver.LXDDriver(None)
        lxd_driver.init_host(None)

        instances = lxd_driver.list_instances()

        self.assertEqual(['mock-instance-1', 'mock-instance-2'], instances)

    def test_spawn(self):
        def container_get(*args, **kwargs):
            raise lxdcore_exceptions.LXDAPIException(MockResponse(404))
        self.client.containers.get.side_effect = container_get

        ctx = context.get_admin_context()
        instance = fake_instance.fake_instance_obj(ctx, name='test')
        image_meta = mock.Mock()
        injected_files = mock.Mock()
        admin_password = mock.Mock()
        network_info = [mock.Mock()]
        block_device_info = mock.Mock()

        lxd_driver = driver.LXDDriver(None)
        lxd_driver.init_host(None)
        # XXX: rockstar (6 Jul 2016) - There are a number of XXX comments
        # related to these calls in spawn. They require some work before we
        # can take out these mocks and follow the real codepaths.
        lxd_driver.setup_image = mock.Mock()
        lxd_driver.vif_driver = mock.Mock()
        lxd_driver.firewall_driver = mock.Mock()
        lxd_driver.create_profile = mock.Mock(return_value={
            'name': instance.name, 'config': {}, 'devices': {}})

        lxd_driver.spawn(
            ctx, instance, image_meta, injected_files, admin_password,
            network_info, block_device_info)

        lxd_driver.setup_image.assert_called_once_with(
            ctx, instance, image_meta)
        lxd_driver.vif_driver.plug.assert_called_once_with(
            instance, network_info[0])
        lxd_driver.create_profile.assert_called_once_with(
            instance, network_info, block_device_info)

    def test_spawn_already_exists(self):
        """InstanceExists is raised if the container already exists."""
        ctx = context.get_admin_context()
        instance = fake_instance.fake_instance_obj(ctx, name='test')
        image_meta = mock.Mock()
        injected_files = mock.Mock()
        admin_password = mock.Mock()

        lxd_driver = driver.LXDDriver(None)
        lxd_driver.init_host(None)

        self.assertRaises(
            exception.InstanceExists,

            lxd_driver.spawn,
            ctx, instance, image_meta, injected_files, admin_password,
            None, None)
