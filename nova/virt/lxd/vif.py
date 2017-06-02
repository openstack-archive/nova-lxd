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

from oslo_log import log as logging

from nova import conf
from nova import exception
from nova.network import model as network_model
from nova.network import os_vif_util

import os_vif

LOG = logging.getLogger(__name__)


def get_vif_devname(vif):
    """Get device name for a given vif."""
    if 'devname' in vif:
        return vif['devname']
    return ("nic" + vif['id'])[:network_model.NIC_NAME_LEN]


def _get_bridge_config(vif):
    return {
        'bridge': vif['network']['bridge'],
        'mac_address': vif['address']}


def _get_ovs_config(vif):
    if (conf.CONF.firewall_driver != 'nova.virt.firewall.NoopFirewallDriver' or
            vif.is_hybrid_plug_enabled()):
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
            return

        # Legacy non-os-vif codepath
        func = getattr(self, 'plug_%s' % vif_type, None)
        if not func:
            raise exception.InternalError(
                "Unexpected vif_type=%s" % vif_type
            )
        func(instance, vif)

    def unplug(self, instance, vif):
        vif_type = vif['type']
        instance_info = os_vif_util.nova_to_osvif_instance(instance)

        # Try os-vif codepath first
        vif_obj = os_vif_util.nova_to_osvif_vif(vif)
        if vif_obj is not None:
            os_vif.unplug(vif_obj, instance_info)
            return

        # Legacy non-os-vif codepath
        func = getattr(self, 'unplug_%s' % vif_type, None)
        if not func:
            raise exception.InternalError(
                "Unexpected vif_type=%s" % vif_type
            )
        func(instance, vif)

    def plug_tap(self, instance, vif):
        '''Dummy plug method for tap devices, creation deferred to LXD'''
        pass

    def unplug_tap(self, instance, vif):
        '''Dummy unplug method for tap devices, deletion deferred to LXD'''
        pass
