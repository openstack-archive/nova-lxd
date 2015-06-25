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
from oslo_utils import units

from pylxd import api
from pylxd import exceptions as lxd_exceptions

from nova.i18n import _
from nova import exception

import container_image
import container_utils

CONF = cfg.CONF
LOG = logging.getLogger(__name__)


class LXDContainerConfig(object):

    def __init__(self):
        self.lxd = api.API()
        self.container_dir = container_utils.LXDContainerDirectories()
        self.container_utils = container_utils.LXDContainerUtils()
        self.container_image = container_image.LXDContainerImage()

    def create_container_profile(self, instance, image_meta, injected_files,
                                 admin_password, network_info, block_device_info,
                                 rescue):
        LOG.debug('Creating profile config')

        name = instance.uuid
        if rescue:
            name = '%s-rescue' % name

        container_profile = self._init_container_config()
        self.add_config(container_profile, 'name', instance.uuid)
        self.configure_profile_config(container_profile, instance)
        self.configure_network_devices(container_profile, instance, network_info)

        return container_profile

    def create_container_config(self, context, instance, image_meta, injected_files,
                                admin_password, network_info, block_device_info, rescue):
        LOG.debug('Creating container config')

        ''' Generate the initial config '''
        name = instance.uuid
        if rescue:
            name = '%s-rescue' % name

        container_config = self._init_container_config()
        self.add_config(container_config, 'name', instance.uuid)
        self.add_config(container_config, 'profiles', ['%s' % instance.uuid])
        self.configure_lxd_image(container_config, instance, image_meta)

        return container_config

    def _init_container_config(self):
        config = {}
        config.setdefault('config', {})
        config.setdefault('devices', {})
        return config

    def configure_profile_config(self, container_profile, instance):
        LOG.debug('Configure LXD profile')

        ''' Set the limits. '''
        flavor = instance.flavor
        mem = flavor.memory_mb * units.Mi
        vcpus = flavor.vcpus
        if mem >= 0:
            self.add_config(container_profile, 'config', 'limits.memory',
                            data='%s' % mem)
        if vcpus >= 1:
            self.add_config(container_profile, 'config', 'limits.cpus',
                            data='%s' % vcpus)

        ''' Basic container configuration. '''
        self.add_config(container_profile, 'config', 'raw.lxc',
                        data='lxc.console.logfile=%s\n'
                            % self.container_dir.get_console_path(instance.uuid))


    def configure_lxd_image(self, container_config, instance, image_meta):
        LOG.debug('Getting LXD image')

        self.add_config(container_config, 'source', 
                        {'type': 'image',
                         'alias': instance.image_ref
                        })

    def configure_network_devices(self, container_profile, instance, network_info):
        LOG.debug('Get network devices')

        ''' ugh this is ugly'''
        for vif in network_info:
            vif_id = vif['id'][:11]
            mac = vif['address']

            bridge = 'qbr%s' % vif_id

            self.add_config(container_profile, 'devices', str(bridge),
                                {'nictype': 'bridged',
                                     'hwaddr': mac,
                                     'parent': bridge,
                                     'type': 'nic'})

    def add_config(self, config, key, value, data=None):
        if not key in config:
            config.setdefault(key, value)
        elif key == 'config':
            config.setdefault('config', {}).\
                setdefault(value, data)
        elif key == 'devices':
            config.setdefault('devices', {}).\
                setdefault(value, data)
        return config
