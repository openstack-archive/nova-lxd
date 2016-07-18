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
from oslo_log import log as logging

import nova.conf
from nova import exception
from nova import i18n
from nova.network import linux_net
from nova.network import model as network_model
from nova import utils

_ = i18n._
_LE = i18n._LE

CONF = nova.conf.CONF

LOG = logging.getLogger(__name__)


class LXDGenericDriver(object):

    def get_vif_devname(self, vif):
        if 'devname' in vif:
            return vif['devname']
        return ("nic" + vif['id'])[:network_model.NIC_NAME_LEN]

    def get_vif_devname_with_prefix(self, vif, prefix):
        devname = self.get_vif_devname(vif)
        return prefix + devname[3:]

    def get_bridge_name(self, vif):
        return vif['network']['bridge']

    def get_ovs_interfaceid(self, vif):
        return vif.get('ovs_interfaceid') or vif['id']

    def get_br_name(self, iface_id):
        return ("qbr" + iface_id)[:network_model.NIC_NAME_LEN]

    def get_veth_pair_names(self, iface_id):
        return (("qvb%s" % iface_id)[:network_model.NIC_NAME_LEN],
                ("qvo%s" % iface_id)[:network_model.NIC_NAME_LEN])

    def get_firewall_required(self, vif):
        if CONF.firewall_driver != "nova.virt.firewall.NoopFirewallDriver":
            return True
        return False

    def get_config(self, instance, vif):
        vif_type = vif['type']

        LOG.debug('vif_type=%(vif_type)s instance=%(instance)s '
                  'vif=%(vif)s',
                  {'vif_type': vif_type, 'instance': instance,
                   'vif': vif})

        if vif_type is None:
            raise exception.NovaException(
                _("vif_type parameter must be present "
                  "for this vif_driver implementation"))
        func = getattr(self, 'get_config_%s' % vif_type, None)
        if not func:
            raise exception.NovaException(
                _("Unexpected vif_type=%s") % vif_type)
        return func(instance, vif)

    def get_config_bridge(self, instance, vif):
        conf = {'bridge': self.get_bridge_name(vif),
                'mac_address': vif['address']}
        return conf

    def get_config_ovs_hybrid(self, instance, vif):
        conf = {'bridge': self.get_br_name(vif['id']),
                'mac_address': vif['address']}

        return conf

    def get_config_ovs_bridge(self, instance, vif):
        conf = {'bridge': self.get_bridge_name(vif),
                'mac_address': vif['address']}

        return conf

    def get_config_ovs(self, instance, vif):
        if self.get_firewall_required(vif) or vif.is_hybrid_plug_enabled():
            return self.get_config_ovs_hybrid(instance, vif)
        else:
            return self.get_config_ovs_bridge(instance, vif)

    def get_config_tap(self, instance, vif):
        conf = {'mac_address': vif['address']}
        return conf

    def plug(self, instance, vif):
        vif_type = vif['type']

        LOG.debug('vif_type=%(vif_type)s instance=%(instance)s '
                  'vif=%(vif)s',
                  {'vif_type': vif_type, 'instance': instance,
                   'vif': vif})

        if vif_type is None:
            raise exception.NovaException(
                _("vif_type parameter must be present "
                  "for this vif_driver implementation"))
        func = getattr(self, 'plug_%s' % vif_type, None)
        if not func:
            raise exception.NovaException(
                _("Unexpected vif_type=%s") % vif_type)
        return func(instance, vif)

    def plug_bridge(self, instance, vif):
        network = vif['network']
        if (not network.get_meta('multi_host', False) and
                network.get_meta('should_create_bridge', False)):
            if network.get_meta('should_create_vlan', False):
                iface = (CONF.vlan_interface or
                         network.get_meta('bridge_interface'))
                LOG.debug('Ensuring vlan %(vlan)s and bridge %(bridge)s',
                          {'vlan': network.get_meta('vlan'),
                           'bridge': self.get_bridge_name(vif)},
                          instance=instance)
                linux_net.LinuxBridgeInterfaceDriver.ensure_vlan_bridge(
                    network.get_meta('vlan'),
                    self.get_bridge_name(vif), iface)
            else:
                iface = (CONF.flat_interface or
                         network.get_meta('bridge_interface'))
                LOG.debug("Ensuring bridge %s",
                          self.get_bridge_name(vif), instance=instance)
                linux_net.LinuxBridgeInterfaceDriver.ensure_bridge(
                    self.get_bridge_name(vif), iface)

    def plug_ovs(self, instance, vif):
        if self.get_firewall_required(vif) or vif.is_hybrid_plug_enabled():
            self.plug_ovs_hybrid(instance, vif)
        else:
            self.plug_ovs_bridge(instance, vif)

    def plug_ovs_bridge(self, instance, vif):
        pass

    def plug_ovs_hybrid(self, instance, vif):
        iface_id = self.get_ovs_interfaceid(vif)
        br_name = self.get_br_name(vif['id'])
        v1_name, v2_name = self.get_veth_pair_names(vif['id'])

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
            linux_net.create_ovs_vif_port(self.get_bridge_name(vif),
                                          v2_name, iface_id,
                                          vif['address'], instance.name)

    def plug_tap(self, instance, vif):
        pass

    def unplug(self, instance, vif):
        vif_type = vif['type']

        LOG.debug('vif_type=%(vif_type)s instance=%(instance)s '
                  'vif=%(vif)s',
                  {'vif_type': vif_type, 'instance': instance,
                   'vif': vif})

        if vif_type is None:
            raise exception.NovaException(
                _("vif_type parameter must be present "
                  "for this vif_driver implementation"))
        func = getattr(self, 'unplug_%s' % vif_type, None)
        if not func:
            raise exception.NovaException(
                _("Unexpected vif_type=%s") % vif_type)
        return func(instance, vif)

    def unplug_ovs(self, instance, vif):
        if self.get_firewall_required(vif) or vif.is_hybrid_plug_enabled():
            self.unplug_ovs_hybrid(instance, vif)
        else:
            self.unplug_ovs_bridge(instance, vif)

    def unplug_ovs_hybrid(self, instance, vif):
        try:
            br_name = self.get_br_name(vif['id'])
            v1_name, v2_name = self.get_veth_pair_names(vif['id'])

            if linux_net.device_exists(br_name):
                utils.execute('brctl', 'delif', br_name, v1_name,
                              run_as_root=True)
                utils.execute('ip', 'link', 'set', br_name, 'down',
                              run_as_root=True)
                utils.execute('brctl', 'delbr', br_name,
                              run_as_root=True)

                linux_net.delete_ovs_vif_port(self.get_bridge_name(vif),
                                              v2_name)
        except processutils.ProcessExecutionError:
            LOG.exception(_LE("Failed while unplugging vif"),
                          instance=instance)

    def unplug_ovs_bridge(self, instance, vif):
        pass

    def unplug_bridge(self, instance, vif):
        pass

    def unplug_tap(self, instance, vif):
        pass
