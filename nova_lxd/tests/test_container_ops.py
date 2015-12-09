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
from nova.virt import fake
from pylxd import exceptions as lxd_exception

from nova_lxd.nova.virt.lxd import container_config
from nova_lxd.nova.virt.lxd import container_ops
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

        self.container_ops = (
            container_ops.LXDContainerOperations(fake.FakeVirtAPI()))
        self.mc = mock.MagicMock()
        config_patcher = mock.patch.object(self.container_ops,
                                           'container_config',
                                           self.mc)
        config_patcher.start()
        self.addCleanup(config_patcher.stop)
        self.mv = mock.MagicMock()
        vif_patcher = mock.patch.object(self.container_ops,
                                        'vif_driver',
                                        self.mv)
        vif_patcher.start()
        self.addCleanup(vif_patcher.stop)

    def test_rescue_defined(self):
        instance = stubs.MockInstance()
        self.ml.container_defined.return_value = True
        self.assertRaises(
            exception.InstanceExists,
            self.container_ops.spawn,
            {}, instance, {}, [], 'secret', rescue=True)
        self.ml.container_defined.called_once_with('fake-instance')

    def test_create_instance_initfail(self):
        instance = stubs._fake_instance()
        self.ml.container_init.side_effect = (
            lxd_exception.APIError('Fake', 500))
        self.assertEqual(None,
                         self.container_ops.create_container(
                             instance, [], [], {}, None, True))

    @stubs.annotated_data(
        ('network_info', False, mock.Mock()),
        ('rescue', False, mock.Mock()),
        ('network-rescue', True, mock.Mock())
    )
    def test_create_container(self, tag, rescue, network_info):
        instance = stubs._fake_instance()
        injected_files = mock.Mock()
        block_device_info = mock.Mock()
        need_vif_plugged = mock.Mock()
        self.ml.container_defined.return_value = True

        with test.nested(
                mock.patch.object(container_config.LXDContainerConfig,
                                  'create_container'),
                mock.patch.object(session.LXDAPISession,
                                  'container_init'),
                mock.patch.object(self.container_ops,
                                  'start_container')
        ) as (
                create_container,
                container_init,
                start_container
        ):
            self.assertEqual(None, self.container_ops.create_container(
                instance, injected_files, network_info,
                block_device_info, rescue, need_vif_plugged))
            create_container.called_assert_called_once_with(
                instance, injected_files, block_device_info,
                rescue)
            print(container_init.method_calls)
            container_init.called_assert_called_once_with(
                container_config, instance.host)

    @mock.patch.object(container_ops, 'utils')
    @stubs.annotated_data(
        {'tag': 'rescue', 'rescue': True, 'is_neutron': False, 'timeout': 0},
        {'tag': 'neutron', 'timeout': 0},
        {'tag': 'neutron_timeout'},
        {'tag': 'neutron_unknown',
         'network_info': [{
             'id': '0123456789abcdef',
         }]},
        {'tag': 'neutron_active', 'network_info':
         [{
             'id': '0123456789abcdef',
             'active': True
         }]},
        {'tag': 'neutron_inactive',
         'network_info': [{
             'id': '0123456789abcdef',
             'active': False
         }],
         'vifs': ('0123456789abcdef',)},
        {'tag': 'neutron_multi',
         'network_info': [{
             'id': '0123456789abcdef',
         }, {
             'id': '123456789abcdef0',
             'active': True
         }, {
             'id': '23456789abcdef01',
             'active': False
         }],
         'vifs': ('23456789abcdef01',)},
        {'tag': 'neutron_failed',
         'network_info': [{
             'id': '0123456789abcdef',
             'active': False
         }],
         'vifs': ('0123456789abcdef',),
         'plug_side_effect': exception.VirtualInterfaceCreateException},
    )
    def test_start_instance(self, mu, tag='', rescue=False, running=False,
                            is_neutron=True, timeout=10, network_info=[],
                            vifs=(), plug_side_effect=None):
        instance = stubs.MockInstance()
        container_config = mock.Mock()
        need_vif_plugged = True
        self.ml.container_running.return_value = running
        self.ml.container_start.return_value = (
            200, {'operation': '/1.0/operations/0123456789'})
        container_ops.CONF.vif_plugging_timeout = timeout
        mu.is_neutron.return_value = is_neutron
        self.mv.plug.side_effect = plug_side_effect
        with mock.patch.object(self.container_ops.virtapi,
                               'wait_for_instance_event') as mw:
            self.assertEqual(
                None,
                self.container_ops.start_container(container_config,
                                                   instance,
                                                   network_info,
                                                   need_vif_plugged))
            mw.assert_called_once_with(
                instance,
                [('network-vif-plugged', vif) for vif in vifs],
                deadline=timeout,
                error_callback=self.container_ops._neutron_failed_callback)
        self.assertEqual(
            [mock.call(instance, viface) for viface in network_info],
            self.mv.plug.call_args_list)
        calls = [
            mock.call.container_start('fake-uuid', 5),
            mock.call.wait_container_operation(
                '/1.0/operations/0123456789', 200, -1)
        ]
        self.assertEqual(calls, self.ml.method_calls[-2:])
