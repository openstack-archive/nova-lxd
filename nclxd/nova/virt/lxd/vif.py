# Copyright (c) 2015 Canonical Ltd
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

from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_log import log as logging


from nova.i18n import _LE, _
from nova import exception
from nova.network import linux_net
from nova.network import model as network_model
from nova import utils


CONF = cfg.CONF

LOG = logging.getLogger(__name__)


class LXDGenericDriver(object):

    def _get_vif_driver(self, vif):
        vif_type = vif['type']
        if vif_type is None:
            raise exception.NovaException(
                _("vif_type parameter must be present "
                  "for this vif_driver implementation"))
        elif vif_type == network_model.VIF_TYPE_OVS:
            return LXDOpenVswitchDriver()
        else:
            return LXDNetworkBridgeDriver()

    def plug(self, instance, vif):
        vif_driver = self._get_vif_driver(vif)
        vif_driver.plug(instance, vif)

    def unplug(self, instance, vif):
        vif_driver = self._get_vif_driver(vif)
        vif_driver.unplug(instance, vif)


class LXDOpenVswitchDriver(object):

    def plug(self, instance, vif, port='ovs'):
        iface_id = self._get_ovs_interfaceid(vif)
        br_name = self._get_br_name(vif['id'])
        v1_name, v2_name = self._get_veth_pair_names(vif['id'])

        if not linux_net.device_exists(br_name):
            utils.execute('brctl', 'addbr', br_name, run_as_root=True)
            utils.execute('brctl', 'setfd', br_name, 0, run_as_root=True)
            utils.execute('brctl', 'stp', br_name, 'off', run_as_root=True)
            utils.execute('tee',
                          ('/sys/class/net/%s/bridge/multicast_snooping' %
                           br_name),
                          process_input='0',
                          run_as_root=True,
                          check_exit_code=[0, 1])

        if not linux_net.device_exists(v2_name):
            linux_net._create_veth_pair(v1_name, v2_name)
            utils.execute('ip', 'link', 'set', br_name, 'up', run_as_root=True)
            utils.execute('brctl', 'addif', br_name, v1_name, run_as_root=True)
            if port == 'ovs':
                linux_net.create_ovs_vif_port(self._get_bridge_name(vif),
                                              v2_name, iface_id,
                                              vif['address'], instance.uuid)
            elif port == 'ivs':
                linux_net.create_ivs_vif_port(v2_name, iface_id,
                                              vif['address'], instance.uuid)

    def unplug(self, instance, vif):
        try:
            br_name = self._get_br_name(vif['id'])
            v1_name, v2_name = self._get_veth_pair_names(vif['id'])

            if linux_net.device_exists(br_name):
                utils.execute('brctl', 'delif', br_name, v1_name,
                              run_as_root=True)
                utils.execute('ip', 'link', 'set', br_name, 'down',
                              run_as_root=True)
                utils.execute('brctl', 'delbr', br_name,
                              run_as_root=True)

            linux_net.delete_ovs_vif_port(self._get_bridge_name(vif),
                                          v2_name)
            if linux_net.device_exists(v2_name):
                utils.execute('ip', 'link', 'set', v2_name, 'down',
                              run_as_root=True)
        except processutils.ProcessExecutionError:
            LOG.exception(_LE("Failed while unplugging vif"),
                          instance=instance)

    def _get_bridge_name(self, vif):
        return vif['network']['bridge']

    def _get_ovs_interfaceid(self, vif):
        return vif.get('ovs_interfaceid') or vif['id']

    def _get_br_name(self, iface_id):
        return ("qbr" + iface_id)[:network_model.NIC_NAME_LEN]

    def _get_veth_pair_names(self, iface_id):
        return (("qvb%s" % iface_id)[:network_model.NIC_NAME_LEN],
                ("qvo%s" % iface_id)[:network_model.NIC_NAME_LEN])


class LXDNetworkBridgeDriver(object):

    def plug(self, instance, vif):
        network = vif['network']
        if (not network.get_meta('multi_host', False) and
                network.get_meta('should_create_bridge', False)):
            if network.get_meta('should_create_vlan', False):
                iface = CONF.vlan_interface or \
                    network.get_meta('bridge_interface')
                LOG.debug('Ensuring vlan %(vlan)s and bridge %(bridge)s',
                          {'vlan': network.get_meta('vlan'),
                           'bridge': vif['network']['bridge']},
                          instance=instance)
                linux_net.LinuxBridgeInterfaceDriver.ensure_vlan_bridge(
                    network.get_meta('vlan'),
                    vif['network']['bridge'],
                    iface)
            else:
                iface = CONF.flat_interface or \
                    network.get_meta('bridge_interface')
                LOG.debug("Ensuring bridge %s",
                          vif['network']['bridge'], instance=instance)
                linux_net.LinuxBridgeInterfaceDriver.ensure_bridge(
                    vif['network']['bridge'],
                    iface)

    def unplug(self, instance, vif):
        pass
