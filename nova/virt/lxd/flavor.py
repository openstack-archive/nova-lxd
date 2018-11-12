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
import os

from nova import exception
from nova import i18n
from nova.virt import driver
from oslo_config import cfg
from oslo_utils import units

from nova.virt.lxd import common
from nova.virt.lxd import vif

_ = i18n._
CONF = cfg.CONF


def _base_config(instance, _):
    instance_attributes = common.InstanceAttributes(instance)
    return {
        'environment.product_name': 'OpenStack Nova',
        'raw.lxc': 'lxc.console.logfile={}\n'.format(
            instance_attributes.console_path),
    }


def _nesting(instance, _):
    if instance.flavor.extra_specs.get('lxd:nested_allowed'):
        return {'security.nesting': 'True'}


def _security(instance, _):
    if instance.flavor.extra_specs.get('lxd:privileged_allowed'):
        return {'security.privileged': 'True'}


def _memory(instance, _):
    mem = instance.memory_mb
    if mem >= 0:
        return {'limits.memory': '{}MB'.format(mem)}


def _cpu(instance, _):
    vcpus = instance.flavor.vcpus
    if vcpus >= 0:
        return {'limits.cpu': str(vcpus)}


def _isolated(instance, client):
    lxd_isolated = instance.flavor.extra_specs.get('lxd:isolated')
    if lxd_isolated:
        extensions = client.host_info.get('api_extensions', [])
        if 'id_map' in extensions:
            return {'security.idmap.isolated': 'True'}
        else:
            msg = _("Host does not support isolated instances")
            raise exception.NovaException(msg)


_CONFIG_FILTER_MAP = [
    _base_config,
    _nesting,
    _security,
    _memory,
    _cpu,
    _isolated,
]


def _root(instance, client, *_):
    """Configure the root disk."""
    device = {'type': 'disk', 'path': '/'}

    # we don't do quotas if the CONF.lxd.pool is set and is dir or lvm, or if
    # the environment['storage'] is dir or lvm.
    if CONF.lxd.pool:
        extensions = client.host_info.get('api_extensions', [])
        if 'storage' in extensions:
            device['pool'] = CONF.lxd.pool
            storage_type = client.storage_pools.get(CONF.lxd.pool).driver
        else:
            msg = _("Host does not have storage pool support")
            raise exception.NovaException(msg)
    else:
        storage_type = client.host_info['environment']['storage']

    if storage_type in ['btrfs', 'zfs']:
        device['size'] = '{}GB'.format(instance.root_gb)

        specs = instance.flavor.extra_specs

        # Bytes and iops are not separate config options in a container
        # profile - we let Bytes take priority over iops if both are set.
        # Align all limits to MiB/s, which should be a sensible middle road.
        if specs.get('quota:disk_read_iops_sec'):
            device['limits.read'] = '{}iops'.format(
                specs['quota:disk_read_iops_sec'])
        if specs.get('quota:disk_write_iops_sec'):
            device['limits.write'] = '{}iops'.format(
                specs['quota:disk_write_iops_sec'])

        if specs.get('quota:disk_read_bytes_sec'):
            device['limits.read'] = '{}MB'.format(
                int(specs['quota:disk_read_bytes_sec']) // units.Mi)
        if specs.get('quota:disk_write_bytes_sec'):
            device['limits.write'] = '{}MB'.format(
                int(specs['quota:disk_write_bytes_sec']) // units.Mi)

        minor_quota_defined = ('limits.write' in device or
                               'limits.read' in device)
        if specs.get('quota:disk_total_iops_sec') and not minor_quota_defined:
            device['limits.max'] = '{}iops'.format(
                specs['quota:disk_total_iops_sec'])
        if specs.get('quota:disk_total_bytes_sec') and not minor_quota_defined:
            device['limits.max'] = '{}MB'.format(
                int(specs['quota:disk_total_bytes_sec']) // units.Mi)

    return {'root': device}


def _ephemeral_storage(instance, client, __, block_info):
    instance_attributes = common.InstanceAttributes(instance)
    ephemeral_storage = driver.block_device_info_get_ephemerals(block_info)
    if ephemeral_storage:
        devices = {}
        for ephemeral in ephemeral_storage:
            ephemeral_src = os.path.join(
                instance_attributes.storage_path,
                ephemeral['virtual_name'])
            device = {
                'path': '/mnt',
                'source': ephemeral_src,
                'type': 'disk',
            }
            if CONF.lxd.pool:
                extensions = client.host_info.get('api_extensions', [])
                if 'storage' in extensions:
                    device['pool'] = CONF.lxd.pool
                else:
                    msg = _("Host does not have storage pool support")
                    raise exception.NovaException(msg)
            devices[ephemeral['virtual_name']] = device
        return devices


def _network(instance, _, network_info, __):
    if not network_info:
        return

    devices = {}
    for vifaddr in network_info:
        cfg = vif.get_config(vifaddr)
        devname = vif.get_vif_devname(vifaddr)
        key = devname
        devices[key] = {
            'nictype': 'physical',
            'hwaddr': str(cfg['mac_address']),
            'parent': vif.get_vif_internal_devname(vifaddr),
            'type': 'nic'
        }

        specs = instance.flavor.extra_specs
        # Since LXD does not implement average NIC IO and number of burst
        # bytes, we take the max(vif_*_average, vif_*_peak) to set the peak
        # network IO and simply ignore the burst bytes.
        # Align values to MBit/s (8 * powers of 1000 in this case), having
        # in mind that the values are recieved in Kilobytes/s.
        vif_inbound_limit = max(
            int(specs.get('quota:vif_inbound_average', 0)),
            int(specs.get('quota:vif_inbound_peak', 0)),
        )
        if vif_inbound_limit:
            devices[key]['limits.ingress'] = '{}Mbit'.format(
                vif_inbound_limit * units.k * 8 // units.M)

        vif_outbound_limit = max(
            int(specs.get('quota:vif_outbound_average', 0)),
            int(specs.get('quota:vif_outbound_peak', 0)),
        )
        if vif_outbound_limit:
            devices[key]['limits.egress'] = '{}Mbit'.format(
                vif_outbound_limit * units.k * 8 // units.M)
    return devices


_DEVICE_FILTER_MAP = [
    _root,
    _ephemeral_storage,
    _network,
]


def to_profile(client, instance, network_info, block_info, update=False):
    """Convert a nova flavor to a lxd profile.

    Every instance container created via nova-lxd has a profile by the
    same name. The profile is sync'd with the configuration of the container.
    When the instance container is deleted, so is the profile.
    """

    name = instance.name

    config = {}
    for f in _CONFIG_FILTER_MAP:
        new = f(instance, client)
        if new:
            config.update(new)

    devices = {}
    for f in _DEVICE_FILTER_MAP:
        new = f(instance, client, network_info, block_info)
        if new:
            devices.update(new)

    if update is True:
        profile = client.profiles.get(name)
        profile.devices = devices
        profile.config = config
        profile.save()
        return profile
    else:
        return client.profiles.create(name, config, devices)
