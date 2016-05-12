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

import copy

import ddt
import mock
from oslo_concurrency import processutils

from nova import exception
from nova.network import model as network_model
from nova import test

from nova.virt.lxd import vif
import stubs


@ddt.ddt
class LXDTestNetworkDriver(test.NoDBTestCase):

    vif_data = {
        'id': '0123456789abcdef',
        'type': network_model.VIF_TYPE_OVS,
        'address': '00:11:22:33:44:55',
        'network': {
            'bridge': 'fakebr'}}

    def setUp(self):
        super(LXDTestNetworkDriver, self).setUp()

        self.vif_driver = vif.LXDGenericDriver()

        mn = mock.Mock()
        net_patcher = mock.patch.object(vif, 'linux_net', mn)
        net_patcher.start()
        self.addCleanup(net_patcher.stop)

        me = mock.Mock()
        net_patcher = mock.patch.object(vif.utils, 'execute', me)
        net_patcher.start()
        self.addCleanup(net_patcher.stop)

        self.mgr = mock.Mock()
        self.mgr.attach_mock(mn, 'net')
        self.mgr.attach_mock(me, 'ex')

    def test_nonetype(self):
        instance = stubs.MockInstance()
        vif_data = {'type': None}
        self.assertRaises(
            exception.NovaException,
            self.vif_driver.plug,
            instance, vif_data)

    def test_get_config_ovs(self):
        instance = stubs._fake_instance()
        vif_data = copy.deepcopy(self.vif_data)

        vif_type = self.vif_driver.get_config(instance, vif_data)
        self.assertEqual(vif_type, {'bridge': 'qbr0123456789a',
                                    'mac_address': '00:11:22:33:44:55'})

    def test_get_config_bridge(self):
        instance = stubs._fake_instance()
        vif_data = copy.deepcopy(self.vif_data)

        vif_type = self.vif_driver.get_config(instance, vif_data)
        self.assertEqual(vif_type, {'bridge': 'qbr0123456789a',
                                    'mac_address': '00:11:22:33:44:55'})

    @stubs.annotated_data(
        ('id', {}, [True, True]),
        ('ovs-id', {'ovs_interfaceid': '123456789abcdef0'}, [True, True]),
        ('no-bridge', {}, [False, True]),
        ('no-v2', {}, [True, False]),
        ('no-bridge-or-v2', {}, [False, False]),
    )
    def test_plug(self, tag, vif_data, exists):
        instance = stubs.MockInstance()
        vif_data = copy.deepcopy(self.vif_data)
        vif_data.update(vif_data)
        self.mgr.net.device_exists.side_effect = exists
        self.assertEqual(
            None,
            self.vif_driver.plug(instance, vif_data))
        calls = [
            mock.call.net.device_exists('qbr0123456789a'),
            mock.call.net.device_exists('qvo0123456789a')
        ]
        if not exists[0]:
            calls[1:1] = [
                mock.call.ex(
                    'brctl', 'addbr', 'qbr0123456789a', run_as_root=True),
                mock.call.ex(
                    'brctl', 'setfd', 'qbr0123456789a', 0, run_as_root=True),
                mock.call.ex('brctl', 'stp', 'qbr0123456789a', 'off',
                             run_as_root=True),
                mock.call.ex('tee',
                             '/sys/class/net/qbr0123456789a/'
                             'bridge/multicast_snooping',
                             process_input='0', run_as_root=True,
                             check_exit_code=[0, 1]),
            ]
        if not exists[1]:
            calls.extend([
                mock.call.net._create_veth_pair('qvb0123456789a',
                                                'qvo0123456789a'),
                mock.call.ex('ip', 'link', 'set', 'qbr0123456789a', 'up',
                             run_as_root=True),
                mock.call.ex('brctl', 'addif', 'qbr0123456789a',
                             'qvb0123456789a', run_as_root=True)])
            calls.append(mock.call.net.create_ovs_vif_port(
                'fakebr', 'qvo0123456789a', '0123456789abcdef',
                '00:11:22:33:44:55', 'fake-uuid'))
        self.assertEqual(calls, self.mgr.method_calls)

    def test_unplug_fail(self):
        instance = stubs.MockInstance()
        vif_data = copy.deepcopy(self.vif_data)
        self.mgr.net.device_exists.side_effect = (
            processutils.ProcessExecutionError)
        self.assertEqual(
            None,
            self.vif_driver.unplug(instance, vif_data))

    @stubs.annotated_data(
        ('id', {}, [True, True]),
        ('ovs-id', {'ovs_interfaceid': '123456789abcdef0'}, [True, True]),
        ('no-bridge', {}, [False, True]),
        ('no-v2', {}, [True, False]),
        ('no-bridge-or-v2', {}, [False, False]),
    )
    def test_unplug(self, tag, vif_data, exists):
        instance = stubs.MockInstance()
        vif = copy.deepcopy(self.vif_data)
        self.mgr.net.device_exists.side_effect = exists
        self.assertEqual(
            None,
            self.vif_driver.unplug(instance, vif))

        calls = [mock.call.net.device_exists('qbr0123456789a')]
        if exists[0]:
            calls[1:1] = [
                mock.call.ex('brctl', 'delif', 'qbr0123456789a',
                             'qvb0123456789a', run_as_root=True),
                mock.call.ex('ip', 'link', 'set', 'qbr0123456789a',
                             'down', run_as_root=True),
                mock.call.ex('brctl', 'delbr', 'qbr0123456789a',
                             run_as_root=True),
                mock.call.net.delete_ovs_vif_port('fakebr', 'qvo0123456789a')
            ]
        self.assertEqual(calls, self.mgr.method_calls)
