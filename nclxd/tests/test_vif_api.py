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
from nova import exception
from nova.network import model as network_model
from nova import test
from oslo_concurrency import processutils

from nclxd.nova.virt.lxd import vif
from nclxd import tests


@ddt.ddt
class LXDTestOVSDriver(test.NoDBTestCase):

    vif_data = {
        'id': '0123456789abcdef',
        'type': network_model.VIF_TYPE_OVS,
        'address': '00:11:22:33:44:55',
        'network': {
            'bridge': 'fakebr'}}

    def setUp(self):
        super(LXDTestOVSDriver, self).setUp()

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
        instance = tests.MockInstance()
        vif_data = {'type': None}
        self.assertRaises(
            exception.NovaException,
            self.vif_driver.plug,
            instance, vif_data)

    @tests.annotated_data(
        ('id', {}, [True, True]),
        ('ovs-id', {'ovs_interfaceid': '123456789abcdef0'}, [True, True]),
        ('no-bridge', {}, [False, True]),
        ('no-v2', {}, [True, False]),
        ('no-bridge-or-v2', {}, [False, False]),
    )
    def test_plug(self, tag, vif_data, exists):
        instance = tests.MockInstance()
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
        instance = tests.MockInstance()
        vif_data = copy.deepcopy(self.vif_data)
        self.mgr.net.device_exists.side_effect = (
            processutils.ProcessExecutionError)
        self.assertEqual(
            None,
            self.vif_driver.unplug(instance, vif_data))

    @tests.annotated_data(
        ('id', {}, [True, True]),
        ('ovs-id', {'ovs_interfaceid': '123456789abcdef0'}, [True, True]),
        ('no-bridge', {}, [False, True]),
        ('no-v2', {}, [True, False]),
        ('no-bridge-or-v2', {}, [False, False]),
    )
    def test_unplug(self, tag, vif_data, exists):
        instance = tests.MockInstance()
        vif = copy.deepcopy(self.vif_data)
        self.mgr.net.device_exists.side_effect = exists
        self.assertEqual(
            None,
            self.vif_driver.unplug(instance, vif))

        calls = [
            mock.call.net.device_exists('qbr0123456789a'),
            mock.call.net.delete_ovs_vif_port('fakebr', 'qvo0123456789a'),
            mock.call.net.device_exists('qvo0123456789a')
        ]
        if exists[0]:
            calls[1:1] = [
                mock.call.ex('brctl', 'delif', 'qbr0123456789a',
                             'qvb0123456789a', run_as_root=True),
                mock.call.ex('ip', 'link', 'set', 'qbr0123456789a', 'down',
                             run_as_root=True),
                mock.call.ex('brctl', 'delbr', 'qbr0123456789a',
                             run_as_root=True)]
        if exists[1]:
            calls.append(
                mock.call.ex('ip', 'link', 'set', 'qvo0123456789a', 'down',
                             run_as_root=True))
        self.assertEqual(calls, self.mgr.method_calls)


@ddt.ddt
@mock.patch.object(vif, 'CONF', tests.MockConf())
class LXDTestBridgeDriver(test.NoDBTestCase):

    vif_data = {
        'type': network_model.VIF_TYPE_BRIDGE,
        'network': {
            'bridge': 'fakebr',
            'meta': {
                'bridge_interface': 'fakebr',
                'vlan': 'fakevlan'}}}

    def setUp(self):
        super(LXDTestBridgeDriver, self).setUp()

        self.vif_driver = vif.LXDGenericDriver()

        self.mn = mock.Mock()
        net_patcher = mock.patch.object(vif, 'linux_net', self.mn)
        net_patcher.start()
        self.addCleanup(net_patcher.stop)

    @tests.annotated_data(
        ('multi', {'multi_host': True}, False, None),
        ('bridge', {'should_create_bridge': True}, False, 'flatif'),
        ('vlan', {'should_create_vlan': True}, False, None),
        ('multi-bridge', {'multi_host': True,
                          'should_create_bridge': True}, False, None),
        ('multi-bridge-vlan', {'multi_host': True,
                               'should_create_bridge': True,
                               'should_create_vlan': True}, False, None),
        ('multi-vlan', {'multi_host': True,
                        'should_create_vlan': True}, False, None),
        ('bridge-vlan', {'should_create_bridge': True,
                         'should_create_vlan': True}, True, 'vlanif'),
        ('bridge-noconf', {'should_create_bridge': True}, False,
         'fakebr', None),
        ('bridge-vlan-noconf', {'should_create_bridge': True,
                                'should_create_vlan': True}, True,
         'fakebr', 'flatif', None),
    )
    def test_plug(self, tag, meta, vlan, iface,
                  flatif='flatif', vlanif='vlanif'):
        instance = tests.MockInstance()
        vif_data = copy.deepcopy(self.vif_data)
        vif_data['network']['meta'].update(meta)
        vif_data['network'] = network_model.Model(vif_data['network'])
        with mock.patch.multiple(vif.CONF, flat_interface=flatif,
                                 vlan_interface=vlanif):
            self.assertEqual(
                None,
                self.vif_driver.plug(instance, vif_data))
            if iface is not None:
                if vlan:
                    (self.mn.LinuxBridgeInterfaceDriver.ensure_vlan_bridge
                     .assert_called_once_with('fakevlan', 'fakebr', iface))
                else:
                    (self.mn.LinuxBridgeInterfaceDriver.ensure_bridge
                     .assert_called_once_with('fakebr', iface))
            else:
                self.assertFalse(self.mn.called)

    def test_unplug(self):
        instance = tests.MockInstance()
        self.assertEqual(None,
                         self.vif_driver.unplug(instance, self.vif_data))
