import contextlib

import mock

from nova import tests
from nova import utils
from nova.network import linux_net
from nclxd.nova.virt.lxd import vif
from nova.network import model as network_model

class LXDGenericDriverTestCase(tests.testCase):
    gateway_bridge_4 = network_model.IP(address='101.168.1.1', type='gateway')
    dns_bridge_4 = network_model.IP(address='8.8.8.8', type=None)
    ips_bridge_4 = [network_model.IP(address='101.168.1.9', type=None)]
    subnet_bridge_4 = network_model.Subnet(cidr='101.168.1.0/24',
                                           dns=[dns_bridge_4],
                                           gateway=gateway_bridge_4,
                                           routes=None,
                                           dhcp_server='191.168.1.1')

    gateway_bridge_6 = network_model.IP(address='101:1db9::1', type='gateway')
    subnet_bridge_6 = network_model.Subnet(cidr='101:1db9::/64',
                                           dns=None,
                                           gateway=gateway_bridge_6,
                                           ips=None,
                                           routes=None)
    network_ovs = network_model.Network(id='network-id-xxx-yyy-zzz',
                                        bridge='br0',
                                        label=None,
                                        subnets=[subnet_bridge_4,
                                                 subnet_bridge_6],
                                        bridge_interface=None,
                                        vlan=99)
    vif_ovs_hybrid = network_model.VIF(id='vif-xxx-yyy-zzz',
                                       address='ca:fe:de:ad:be:ef',
                                       network=network_ovs,
                                       type=network_model.VIF_TYPE_OVS,
                                       details={'ovs_hybrid_plug': True,
                                                'port_filter': True},
                                       devname='tap-xxx-yyy-zzz',
                                       ovs_interfaceid='aaa-bbb-ccc')
    def test_plug_ovs_hybrid(self):
        calls = {
            'device_exists': [mock.call('qbrvif-xxx-yyy'),
                              mock.call('qvovif-xxx-yyy')],
            '_create_veth_pair': [mock.call('qvbvif-xxx-yyy',
                                            'qvovif-xxx-yyy')],
            'execute': [mock.call('brctl', 'addbr', 'qbrvif-xxx-yyy',
                                  run_as_root=True),
                        mock.call('brctl', 'setfd', 'qbrvif-xxx-yyy', 0,
                                  run_as_root=True),
                        mock.call('brctl', 'stp', 'qbrvif-xxx-yyy', 'off',
                                  run_as_root=True),
                        mock.call('tee', ('/sys/class/net/qbrvif-xxx-yyy'
                                          '/bridge/multicast_snooping'),
                                  process_input='0', run_as_root=True,
                                  check_exit_code=[0, 1]),
                        mock.call('ip', 'link', 'set', 'qbrvif-xxx-yyy', 'up',
                                  run_as_root=True),
                        mock.call('brctl', 'addif', 'qbrvif-xxx-yyy',
                                  'qvbvif-xxx-yyy', run_as_root=True)],
            'create_ovs_vif_port': [mock.call('br0',
                                              'qvovif-xxx-yyy', 'aaa-bbb-ccc',
                                              'ca:fe:de:ad:be:ef',
                                              'instance-uuid')]
        }
        with contextlib.nested(
                mock.patch.object(linux_net, 'device_exists',
                                  return_value=False),
                mock.patch.object(utils, 'execute'),
                mock.patch.object(linux_net, '_create_veth_pair'),
                mock.patch.object(linux_net, 'create_ovs_vif_port')
        ) as (device_exists, execute, _create_veth_pair, create_ovs_vif_port):
            d = vif.LXDGenericDriver()
            d.plug_ovs_hybrid(self.instance, self.vif_ovs)
            device_exists.assert_has_calls(calls['device_exists'])
            _create_veth_pair.assert_has_calls(calls['_create_veth_pair'])
            execute.assert_has_calls(calls['execute'])
            create_ovs_vif_port.assert_has_calls(calls['create_ovs_vif_port'])
