import contextlib

import mock

from nova import test
from nova import utils
from nova.network import linux_net
from nclxd.nova.virt.lxd import vif
from nova.network import model as network_model

class LXDGenericDriverTestCase(test.NoDBTestCase):
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

    instance = {
        'name': 'instance-name',
        'uuid': 'instance-uuid'
    }
