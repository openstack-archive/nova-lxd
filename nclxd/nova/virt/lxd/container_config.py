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

from nova.api.metadata import base as instance_metadata
from nova import exception
from nova import i18n
from nova.virt import configdrive
from oslo.utils import excutils
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import units

import container_image
import container_utils

_ = i18n._
_LE = i18n._LE
_LI = i18n._LI

CONF = cfg.CONF
LOG = logging.getLogger(__name__)


class LXDContainerConfig(object):

    def __init__(self):
        self.container_dir = container_utils.LXDContainerDirectories()
        self.container_utils = container_utils.LXDContainerUtils()
        self.container_image = container_image.LXDContainerImage()

    def _init_container_config(self):
        config = {}
        config.setdefault('config', {})
        config.setdefault('devices', {})
        return config

    def configure_container(self, context, instance, network_info, image_meta,
                            name_label=None, rescue=False):
        LOG.debug('Creating LXD container')

        name = instance.name
        if rescue:
            name = name_label

        container_config = self._init_container_config()
        container_config = self.add_config(container_config, 'name',
                                           name)
        container_config = self.add_config(container_config, 'profiles',
                                           [str(CONF.lxd.lxd_default_profile)])
        container_config = self.configure_container_config(
            container_config, instance)

        ''' Create an LXD image '''
        self.container_image.fetch_image(context, instance, image_meta)
        container_config = (
            self.add_config(container_config, 'source',
                            self.configure_lxd_image(container_config,
                                                     instance, image_meta)))

        return container_config

    def configure_container_config(self, container_config, instance):
        LOG.debug('Configure LXD container')

        ''' Set the limits. '''
        flavor = instance.flavor
        mem = flavor.memory_mb * units.Mi
        vcpus = flavor.vcpus
        if mem >= 0:
            self.add_config(container_config, 'config', 'limits.memory',
                            data='%s' % mem)
        if vcpus >= 1:
            self.add_config(container_config, 'config', 'limits.cpus',
                            data='%s' % vcpus)

        ''' Basic container configuration. '''
        self.add_config(container_config, 'config', 'raw.lxc',
                        data='lxc.console.logfile=%s\n'
                        % self.container_dir.get_console_path(instance.name))
        return container_config

    def configure_lxd_image(self, container_config, instance, image_meta):
        LOG.debug('Getting LXD image')

        self.add_config(container_config, 'source',
                        {'type': 'image',
                         'alias': str(image_meta.get('name'))
                         })
        return container_config

    def configure_network_devices(self, container_config,
                                  instance, network_info):
        LOG.debug('Get network devices')

        ''' ugh this is ugly'''
        for vif in network_info:
            vif_id = vif['id'][:11]
            mac = vif['address']

            bridge = 'qbr%s' % vif_id

            self.add_config(container_config, 'devices', bridge,
                            data={'nictype': 'bridged',
                                  'hwaddr': mac,
                                  'parent': bridge,
                                  'type': 'nic'})

        return container_config

    def configure_disk_path(self, container_config, vfs_type, instance):
        LOG.debug('Create disk path')
        config_drive = self.container_dir.get_container_configdrive(
            instance.name)
        self.add_config(container_config, 'devices', str(vfs_type),
                        data={'path': 'mnt',
                              'source': config_drive,
                              'type': 'disk'})
        return container_config

    def configure_container_rescuedisk(self, container_config, instance):
        LOG.debug('Create rescue disk')
        rescue_path = self.container_dir.get_container_rootfs(instance.name)
        self.add_config(container_config, 'devices', 'rescue',
                        data={'path': 'mnt',
                              'source': rescue_path,
                              'type': 'disk'})
        return container_config

    def configure_container_configdrive(self, container_config, instance,
                                        injected_files, admin_password):
        LOG.debug('Create config drive')
        if CONF.config_drive_format not in ('fs', None):
            msg = (_('Invalid config drive format: %s')
                   % CONF.config_drive_format)
            raise exception.InstancePowerOnFailure(reason=msg)

        LOG.info(_LI('Using config drive for instance'), instance=instance)
        extra_md = {}

        inst_md = instance_metadata.InstanceMetadata(instance,
                                                     content=injected_files,
                                                     extra_md=extra_md)
        name = instance.name
        try:
            with configdrive.ConfigDriveBuilder(instance_md=inst_md) as cdb:
                container_configdrive = (
                    self.container_dir.get_container_configdrive(name)
                )
                cdb.make_drive(container_configdrive)
                container_config = self.configure_disk_path(container_config,
                                                            'configdrive',
                                                            instance)
        except Exception as e:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Creating config drive failed with error: %s'),
                          e, instance=instance)

        return container_config

    def add_config(self, config, key, value, data=None):
        if key == 'config':
            config.setdefault('config', {}).setdefault(value, data)
        elif key == 'devices':
            config.setdefault('devices', {}).setdefault(value, data)
        elif key not in config:
            config.setdefault(key, value)
        return config
