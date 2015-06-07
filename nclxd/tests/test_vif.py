import contextlib

import mock
from oslo_config import cfg

from nova import test
from nova.network import linux_net
from nova.network import model as network_model
from nova.virt.lxd import driver as lxd_driver
from nova import exception
from nova import utils

cfg = cfg.CONF

class LXDVifTestCase(test.NoDBTestCase):
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

      network_bridge = network_model.Network(id='network-id-xxx-yyy-zzz',
                                           bridge='br0',
                                           label=None,
                                           subnets=[subnet_bridge_4,
                                                    subnet_bridge_6],
                                           bridge_interface='eth0',
                                           vlan=99)

      def setUp(self):
          super(LXDVifTestCase(), self).setUp()
          self.executes = []

          def fake_execute(*cmd, **kwargs):
            self.executes.append(cmd)
            return None, None

          self.stubs.Set(utils, 'execute', fake_execute)
