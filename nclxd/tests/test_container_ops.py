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
from nova import exception
from nova import test
from pylxd import exceptions as lxd_exceptions

from nclxd.nova.virt.lxd import container_ops
from nclxd.nova.virt.lxd import container_utils
from nclxd import tests


@ddt.ddt
@mock.patch.object(container_ops, 'CONF', tests.MockConf())
@mock.patch.object(container_utils, 'CONF', tests.MockConf())
class LXDTestContainerOps(test.NoDBTestCase):

    @mock.patch.object(container_utils, 'CONF', tests.MockConf())
    def setUp(self):
        super(LXDTestContainerOps, self).setUp()
        self.ml = tests.lxd_mock()
        lxd_patcher = mock.patch('pylxd.api.API',
                                 mock.Mock(return_value=self.ml))
        lxd_patcher.start()
        self.addCleanup(lxd_patcher.stop)

        self.container_ops = container_ops.LXDContainerOperations(mock.Mock())
        self.mc = mock.MagicMock()
        config_patcher = mock.patch.object(self.container_ops,
                                           'container_config',
                                           self.mc)
        config_patcher.start()
        self.addCleanup(config_patcher.stop)

    def test_init_host(self):
        self.assertEqual(
            True,
            self.container_ops.init_host(None)
        )

    @tests.annotated_data(
        ('bad_profile', {'profile_list.return_value': ['bad_profile']}),
        ('profile_fail', {'profile_list.side_effect':
                          lxd_exceptions.APIError('Fake', 500)}),
        ('no_ping', {'host_ping.return_value': False}),
        ('ping_fail', {'host_ping.side_effect':
                       lxd_exceptions.APIError('Fake', 500)}),
    )
    def test_init_host_fail(self, tag, config):
        self.ml.configure_mock(**config)
        self.assertRaises(
            exception.HostNotFound,
            self.container_ops.init_host,
            None
        )

    def test_list_instances(self):
        self.assertEqual(['mock-instance-1', 'mock-instance-2'],
                         self.container_ops.list_instances())

    def test_list_instances_fail(self):
        self.ml.configure_mock(
            **{'container_list.side_effect':
               lxd_exceptions.APIError('Fake', 500)})
        self.assertRaises(
            exception.NovaException,
            self.container_ops.list_instances
        )

    @tests.annotated_data(
        ('exists', [True], exception.InstanceExists, False, 'mock-instance'),
        ('exists_rescue', [True], exception.InstanceExists,
         True, 'fake-instance'),
        ('fail', lxd_exceptions.APIError('Fake', 500),
         exception.NovaException, False, 'mock-instance')
    )
    def test_spawn_defined(self, tag, side_effect, expected, rescue, name):
        instance = tests.MockInstance()
        self.ml.container_defined.side_effect = side_effect
        self.assertRaises(
            expected,
            self.container_ops.spawn,
            {}, instance, {}, [], 'secret',
            name_label='fake-instance', rescue=rescue)
        self.ml.container_defined.called_once_with(name)

    def test_spawn_new(self):
        context = mock.Mock()
        instance = tests.MockInstance()
        image_meta = mock.Mock()
        injected_files = mock.Mock()
        network_info = mock.Mock()
        block_device_info = mock.Mock()
        self.ml.container_defined.return_value = False
        with mock.patch.object(self.container_ops, 'create_instance') as mc:
            self.assertEqual(
                None,
                self.container_ops.spawn(
                    context, instance, image_meta, injected_files, 'secret',
                    network_info, block_device_info, 'fake_instance', False))
            mc.assert_called_once_with(
                context, instance, image_meta, injected_files, 'secret',
                network_info, block_device_info, 'fake_instance', False)
