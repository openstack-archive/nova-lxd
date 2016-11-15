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
import mock

from nova import context
from nova import exception
from nova.network import model as network_model
from nova import test
from nova.tests.unit import fake_instance
from nova.virt.lxd import vif

GATEWAY = network_model.IP(address='101.168.1.1', type='gateway')
DNS_BRIDGE = network_model.IP(address='8.8.8.8', type=None)
SUBNET = network_model.Subnet(
    cidr='101.168.1.0/24', dns=[DNS_BRIDGE], gateway=GATEWAY,
    routes=None, dhcp_server='191.168.1.1')
NETWORK = network_model.Network(
    id='network-id-xxx-yyy-zzz', bridge='br0', label=None,
    subnets=[SUBNET], bridge_interface=None, vlan=99, mtu=1000)
VIF = network_model.VIF(
    id='0123456789abcdef', address='ca:fe:de:ad:be:ef',
    network=NETWORK, type=network_model.VIF_TYPE_OVS,
    devname='tap-012-345-678', ovs_interfaceid='9abc-def-000')
INSTANCE = fake_instance.fake_instance_obj(
    context.get_admin_context(), name='test')


class GetVifDevnameTest(test.NoDBTestCase):
    """Tests for get_vif_devname."""

    def test_get_vif_devname_devname_exists(self):
        an_vif = {
            'id': '0123456789abcdef',
            'devname': 'oth1',
        }

        devname = vif.get_vif_devname(an_vif)

        self.assertEqual('oth1', devname)

    def test_get_vif_devname_devname_nonexistent(self):
        an_vif = {
            'id': '0123456789abcdef',
        }

        devname = vif.get_vif_devname(an_vif)

        self.assertEqual('nic0123456789a', devname)


class GetConfigTest(test.NoDBTestCase):
    """Tests for get_config."""

    def setUp(self):
        super(GetConfigTest, self).setUp()
        self.CONF_patcher = mock.patch('nova.virt.lxd.vif.conf.CONF')
        self.CONF = self.CONF_patcher.start()
        self.CONF.firewall_driver = 'nova.virt.firewall.NoopFirewallDriver'

    def tearDown(self):
        super(GetConfigTest, self).tearDown()
        self.CONF_patcher.stop()

    def test_get_config_bad_vif_type(self):
        """Unsupported vif types raise an exception."""
        an_vif = network_model.VIF(
            id='0123456789abcdef', address='ca:fe:de:ad:be:ef',
            network=NETWORK, type='invalid',
            devname='tap-012-345-678', ovs_interfaceid='9abc-def-000')

        self.assertRaises(
            exception.NovaException, vif.get_config, an_vif)

    def test_get_config_bridge(self):
        expected = {'bridge': 'br0', 'mac_address': 'ca:fe:de:ad:be:ef'}
        an_vif = network_model.VIF(
            id='0123456789abcdef', address='ca:fe:de:ad:be:ef',
            network=NETWORK, type='bridge',
            devname='tap-012-345-678', ovs_interfaceid='9abc-def-000')

        config = vif.get_config(an_vif)

        self.assertEqual(expected, config)

    def test_get_config_ovs_bridge(self):
        expected = {
            'bridge': 'br0', 'mac_address': 'ca:fe:de:ad:be:ef'}
        an_vif = network_model.VIF(
            id='0123456789abcdef', address='ca:fe:de:ad:be:ef',
            network=NETWORK, type='ovs',
            devname='tap-012-345-678', ovs_interfaceid='9abc-def-000')

        config = vif.get_config(an_vif)

        self.assertEqual(expected, config)

    def test_get_config_ovs_hybrid(self):
        self.CONF.firewall_driver = 'AnFirewallDriver'

        expected = {
            'bridge': 'qbr0123456789a', 'mac_address': 'ca:fe:de:ad:be:ef'}
        an_vif = network_model.VIF(
            id='0123456789abcdef', address='ca:fe:de:ad:be:ef',
            network=NETWORK, type='ovs',
            devname='tap-012-345-678', ovs_interfaceid='9abc-def-000')

        config = vif.get_config(an_vif)

        self.assertEqual(expected, config)

    def test_get_config_tap(self):
        expected = {'mac_address': 'ca:fe:de:ad:be:ef'}
        an_vif = network_model.VIF(
            id='0123456789abcdef', address='ca:fe:de:ad:be:ef',
            network=NETWORK, type='tap',
            devname='tap-012-345-678', ovs_interfaceid='9abc-def-000')

        config = vif.get_config(an_vif)

        self.assertEqual(expected, config)


class LXDGenericVifDriverTest(test.NoDBTestCase):
    """Tests for LXDGenericVifDriver."""

    def setUp(self):
        super(LXDGenericVifDriverTest, self).setUp()
        self.vif_driver = vif.LXDGenericVifDriver()

    @mock.patch('nova.virt.lxd.vif.os_vif')
    def test_plug(self, os_vif):
        self.vif_driver.plug(INSTANCE, VIF)

        self.assertEqual(
            'tap-012-345-678', os_vif.plug.call_args[0][0].vif_name)
        self.assertEqual(
            'instance-00000001', os_vif.plug.call_args[0][1].name)

    @mock.patch('nova.virt.lxd.vif.os_vif')
    def test_unplug(self, os_vif):
        self.vif_driver.unplug(INSTANCE, VIF)

        self.assertEqual(
            'tap-012-345-678', os_vif.unplug.call_args[0][0].vif_name)
        self.assertEqual(
            'instance-00000001', os_vif.unplug.call_args[0][1].name)
