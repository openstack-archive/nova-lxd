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

from nova import conf
from nova import exception
from nova import utils
from nova.network import linux_net
from nova.network import model as network_model
from nova.network import os_vif_util

import os_vif


CONF = conf.CONF

LOG = logging.getLogger(__name__)


def get_vif_devname(vif):
    """Get device name for a given vif."""
    if 'devname' in vif:
        return vif['devname']
    return ("nic" + vif['id'])[:network_model.NIC_NAME_LEN]


def get_vif_internal_devname(vif):
    """Get the internal device name for a given vif."""
    return get_vif_devname(vif).replace('tap', 'tin')


def _create_veth_pair(dev1_name, dev2_name, mtu=None):
    """Create a pair of veth devices with the specified names,
    deleting any previous devices with those names.
    """
    for dev in [dev1_name, dev2_name]:
        linux_net.delete_net_dev(dev)

    utils.execute('ip', 'link', 'add', dev1_name, 'type', 'veth', 'peer',
                  'name', dev2_name, run_as_root=True)

    for dev in [dev1_name, dev2_name]:
        utils.execute('ip', 'link', 'set', dev, 'up', run_as_root=True)
        linux_net._set_device_mtu(dev, mtu)


def _add_bridge_port(bridge, dev):
    utils.execute('brctl', 'addif', bridge, dev, run_as_root=True)


def _is_no_op_firewall():
    return CONF.firewall_driver == "nova.virt.firewall.NoopFirewallDriver"


def _is_ovs_vif_port(vif):
    return vif['type'] == 'ovs' and not vif.is_hybrid_plug_enabled()


def _get_bridge_config(vif):
    return {
        'bridge': vif['network']['bridge'],
        'mac_address': vif['address']}


def _get_ovs_config(vif):
    if not _is_no_op_firewall() or vif.is_hybrid_plug_enabled():
        return {
            'bridge': ('qbr{}'.format(vif['id']))[:network_model.NIC_NAME_LEN],
            'mac_address': vif['address']}
    else:
        return {
            'bridge': vif['network']['bridge'],
            'mac_address': vif['address']}


def _get_tap_config(vif):
    return {'mac_address': vif['address']}


CONFIG_GENERATORS = {
    'bridge': _get_bridge_config,
    'ovs': _get_ovs_config,
    'tap': _get_tap_config,
}


def get_config(vif):
    """Get LXD specific config for a vif."""
    vif_type = vif['type']

    try:
        return CONFIG_GENERATORS[vif_type](vif)
    except KeyError:
        raise exception.NovaException(
            'Unsupported vif type: {}'.format(vif_type))


# VIF_TYPE_OVS = 'ovs'
# VIF_TYPE_BRIDGE = 'bridge'
def _post_plug_wiring_veth_and_bridge(instance, vif):
    config = get_config(vif)
    network = vif.get('network')
    mtu = network.get_meta('mtu') if network else None
    v1_name = get_vif_devname(vif)
    v2_name = get_vif_internal_devname(vif)
    if not linux_net.device_exists(v1_name):
        _create_veth_pair(v1_name, v2_name, mtu)
        if _is_ovs_vif_port(vif):
            # NOTE(jamespage): wire tap device directly to ovs bridge
            linux_net.create_ovs_vif_port(vif['network']['bridge'],
                                          v1_name,
                                          vif['id'],
                                          vif['address'],
                                          instance.uuid,
                                          mtu)
        else:
            # NOTE(jamespage): wire tap device linux bridge
            _add_bridge_port(config['bridge'], v1_name)
    else:
        linux_net._set_device_mtu(v1_name, mtu)


POST_PLUG_WIRING = {
    'bridge': _post_plug_wiring_veth_and_bridge,
    'ovs': _post_plug_wiring_veth_and_bridge,
}


def _post_plug_wiring(instance, vif):
    """Perform nova-lxd specific post os-vif plug processing

    :param vif: a nova.network.model.VIF instance

    Perform any post os-vif plug wiring requires to network
    the instance LXD container with the underlying Neutron
    network infrastructure
    """

    LOG.debug("Performing post plug wiring for VIF %s", vif)
    vif_type = vif['type']

    try:
        POST_PLUG_WIRING[vif_type](instance, vif)
    except KeyError:
        LOG.debug("No post plug wiring step "
                  "for vif type: {}".format(vif_type))


# VIF_TYPE_OVS = 'ovs'
# VIF_TYPE_BRIDGE = 'bridge'
def _post_unplug_wiring_delete_veth(instance, vif):
    v1_name = get_vif_devname(vif)
    try:
        if _is_ovs_vif_port(vif):
            linux_net.delete_ovs_vif_port(vif['network']['bridge'],
                                          v1_name, True)
        else:
            linux_net.delete_net_dev(v1_name)
    except processutils.ProcessExecutionError:
        LOG.exception("Failed to delete veth for vif",
                      vif=vif)


POST_UNPLUG_WIRING = {
    'bridge': _post_unplug_wiring_delete_veth,
    'ovs': _post_unplug_wiring_delete_veth,
}


def _post_unplug_wiring(instance, vif):
    """Perform nova-lxd specific post os-vif unplug processing

    :param vif: a nova.network.model.VIF instance

    Perform any post os-vif unplug wiring requires to remove
    network interfaces assocaited with a lxd container.
    """

    LOG.debug("Performing post unplug wiring for VIF %s", vif)
    vif_type = vif['type']

    try:
        POST_UNPLUG_WIRING[vif_type](instance, vif)
    except KeyError:
        LOG.debug("No post unplug wiring step "
                  "for vif type: {}".format(vif_type))


class LXDGenericVifDriver(object):
    """Generic VIF driver for LXD networking."""

    def __init__(self):
        os_vif.initialize()

    def plug(self, instance, vif):
        vif_type = vif['type']
        instance_info = os_vif_util.nova_to_osvif_instance(instance)

        # Try os-vif codepath first
        vif_obj = os_vif_util.nova_to_osvif_vif(vif)
        if vif_obj is not None:
            os_vif.plug(vif_obj, instance_info)
        else:
            # Legacy non-os-vif codepath
            func = getattr(self, 'plug_%s' % vif_type, None)
            if not func:
                raise exception.InternalError(
                    "Unexpected vif_type=%s" % vif_type
                )
            func(instance, vif)

        _post_plug_wiring(instance, vif)

    def unplug(self, instance, vif):
        vif_type = vif['type']
        instance_info = os_vif_util.nova_to_osvif_instance(instance)

        # Try os-vif codepath first
        vif_obj = os_vif_util.nova_to_osvif_vif(vif)
        if vif_obj is not None:
            os_vif.unplug(vif_obj, instance_info)
        else:
            # Legacy non-os-vif codepath
            func = getattr(self, 'unplug_%s' % vif_type, None)
            if not func:
                raise exception.InternalError(
                    "Unexpected vif_type=%s" % vif_type
                )
            func(instance, vif)

        _post_unplug_wiring(instance, vif)

    def plug_tap(self, instance, vif):
        """Plug a VIF_TYPE_TAP virtual interface."""
        v1_name = get_vif_devname(vif)
        v2_name = get_vif_internal_devname(vif)
        network = vif.get('network')
        mtu = network.get_meta('mtu') if network else None
        # NOTE(jamespage): For nova-lxd this is really a veth pair
        #                  so that a) security rules get applied on the host
        #                  and b) that the container can still be wired.
        if not linux_net.device_exists(v1_name):
            _create_veth_pair(v1_name, v2_name, mtu)
        else:
            linux_net._set_device_mtu(v1_name, mtu)

    def unplug_tap(self, instance, vif):
        """Unplug a VIF_TYPE_TAP virtual interface."""
        dev = get_vif_devname(vif)
        try:
            linux_net.delete_net_dev(dev)
        except processutils.ProcessExecutionError:
            LOG.exception("Failed while unplugging vif",
                          instance=instance)
