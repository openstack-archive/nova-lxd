# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# Copyright (c) 2010 Citrix Systems, Inc.
# Copyright 2011 Justin Santa Barbara
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

from oslo_config import cfg
from oslo_log import log as logging

from nova import exception
from nova.i18n import _

import container_utils

CONF = cfg.CONF
LOG = logging.getLogger(__name__)


class LXDProfile(object):
    def __init__(self, lxd):
        self.lxd = lxd

        ''' Prefetch information that we need about the host.'''
        self.host = self.lxd.host_info()

    def profile_create(self, instance, network_info):
        LOG.debug('Creating host profile')

        profile = {'name': instance.uuid,
                   'config': {'raw.lxc':
                              'lxc.console.logfile = %s\n'
                                % container_utils.get_console_path(instance)}
        }
        if network_info:
            profile['devices'] = self._get_network_devices(network_info)
        if instance:
            profile = self._get_container_limits(instance, profile)

        if not self.lxd.profile_create(profile):
            msg = _('Failed to create profile')
            raise exception.NovaException(msg)

    def profile_delete(self, instance):
        if not self.lxd.profile_delete(instance.uuid):
            msg = _('Unable to delete profile')
            raise exception.NovaException(msg)

    def _get_container_limits(self, instance, profile):
        LOG.debug("Setting container limits")

        if instance.vcpus >= 1:
            profile['config'].update({'limits.cpus': '%s'
                                       % instance.vcpus})

        if instance.memory_mb >= 0:
            profile['config'].update({'limits.memory': instance.memory_mb})
        return profile

    def _get_network_devices(self, network_info):
        for vif in network_info:
            vif_id = vif['id'][:11]
            vif_type = vif['type']
            bridge = vif['network']['bridge']
            mac = vif['address']

        if vif_type == 'ovs':
            bridge = 'qbr%s' % vif_id

        return {'eth0': {'nictype': 'bridged',
                         'hwaddr': mac,
                         'parent': bridge,
                         'type': 'nic'}}
