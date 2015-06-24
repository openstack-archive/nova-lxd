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

    def create_container(self, context, instance, image_meta, network_info, rescue,
                         injected_files=None, admin_password=None,
                         block_device_info=None):
        LOG.debug('creating container')

        self.create_container_profile(instance, image_meta, injected_files,
                                      admin_password, network_info, block_device_info,
                                      rescue)
        container_config = self.create_container_config(context, instance, image_meta,
                                                        injected_files, admin_password,
                                                        network_info, block_device_info,
                                                        rescue)

        return container_config

    def create_container_profile(self, instance, image_meta, injected_files,
                                 admin_password, network_info, block_device_info,
                                 rescue):
        LOG.debug('Creating profile config')

        name = instance.uuid
        if rescue:
            name = '%s-rescue' % name

        container_profile = {}
        self.add_config(container_profile, 'name', name)
        self.add_config(container_profile, 'config', 
                        {'raw.lxc':
                         'lxc.console.logfile = %s\n'
                         % self.container_dir.get_console_path(
                            instance.uuid)})

        self.add_config(container_profile, 'devices', {})
        if network_info:
            self.get_network_devices(container_profile, instance, 
                                     network_info)

        self.container_utils.profile_create(container_profile)

    def create_container_config(self, context, instance, image_meta, injected_files,
                                admin_password, network_info, block_device_info, rescue):
        LOG.debug('Creating container config')

        ''' Generate the initial config '''
        name = instance.uuid
        if rescue:
            name = '%s-rescue' % name

        container_config = {}
        self.add_config(container_config, 'name', name)
        self.add_config(container_config, 'profiles',  ['%s' % name])

        ''' Fetch the image from glance and configure it '''
        self.container_image.fetch_image(context, instance)
        self.add_config(container_config, 'source', 
                        self.get_lxd_image(instance, image_meta))

        return container_config

    def get_lxd_profiles(self, instance):
        LOG.debug('get lxd profiles')
        profiles = []
        return profiles.append(instance.uuid)


    def get_lxd_config(self, instance, image_meta, container_profile):
        LOG.debug('get_lxd_limits')

        flavor = instance.get_flavor()
        mem = flavor.memory_mb * units.Mi
        vpcus = flavor.vcpus
        if vcpus >= 1:
            self.add_value_to_config(container_profile, 'config',
                                     {'limits.cpus': '%s' % vcpus})
        if mem >= 0:
            self.add_value_to_config(container_profile, 'config',
                                     {'limits.memory': '%s' % mem})

    def get_lxd_image(self, instance, image_meta):
        LOG.debug('Getting LXD image')

        img_meta_prop = image_meta.get('properties', {}) if image_meta else {}
        img_type = img_meta_prop.get('image_type', 'default')

        if img_type == 'default':
            return {'type': 'image',
                    'alias': instance.image_ref}

    def get_network_devices(self, container_profile, instance, network_info):
        LOG.debug('Get network devices')

        ''' ugh this is ugly'''
        for vif in network_info:
            vif_id = vif['id'][:11]
            mac = vif['address']

            bridge = 'qbr%s' % vif_id

            self.add_config(container_profile, 'devices', bridge,
                                {'nictype': 'bridged',
                                     'hwaddr': mac,
                                     'parent': bridge,
                                     'type': 'nic'})

    def add_config(self, config, key, value, devices=None):
        if not key in config:
            config.setdefault(key, value)
        else:
            if key == 'devices':
                config.setdefault('devices', {}).\
                    setdefault(value, devices)
