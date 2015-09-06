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

import collections
import pprint

from nova.api.metadata import base as instance_metadata
from nova import exception
from nova import i18n
from nova.virt import configdrive
from nova.virt import driver
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import fileutils
from oslo_utils import units
import six

from nclxd.nova.virt.lxd import container_client
from nclxd.nova.virt.lxd import container_image
from nclxd.nova.virt.lxd import container_utils
from nclxd.nova.virt.lxd import vif

_ = i18n._
_LE = i18n._LE
_LI = i18n._LI

CONF = cfg.CONF
CONF.import_opt('my_ip', 'nova.netconf')
LOG = logging.getLogger(__name__)


class LXDContainerConfig(object):

    def __init__(self):
        self.container_dir = container_utils.LXDContainerDirectories()
        self.container_client = container_client.LXDContainerClient()
        self.container_image = container_image.LXDContainerImage()
        self.vif_driver = vif.LXDGenericDriver()

    def _init_container_config(self):
        config = {}
        config.setdefault('config', {})
        config.setdefault('devices', {})
        return config

    def create_container(self, context, instance, image_meta, injected_files,
                        admin_password, network_info, block_device_info,
                        name_label=None, rescue=False, host=None):

        LOG.debug('Creating instance')

        name = instance.uuid
        if rescue:
            name = name_label

        # Ensure the directory exists and is writable
        fileutils.ensure_tree(
            self.container_dir.get_instance_dir(name))

        # Check to see if we are using swap.
        swap = driver.block_device_info_get_swap(block_device_info)
        if driver.swap_is_usable(swap):
            msg = _('Swap space is not supported by LXD.')
            raise exception.NovaException(msg)

        # Check to see if ephemeral block devices exist.
        ephemeral_gb = instance.ephemeral_gb
        if ephemeral_gb > 0:
            msg = _('Ephemeral block devices is not supported.')
            raise exception.NovaException(msg)

        name = instance.uuid
        if rescue:
            name = name_label

        container_config = self._init_container_config()
        container_config = self.configure_container_config(name,
            container_config, instance)

        ''' Create an LXD image '''
        self.container_image.setup_image(context, instance, image_meta, host=host)
        container_config = (
            self.add_config(container_config, 'source',
                            self.configure_lxd_image(container_config,
                                                     instance, image_meta)))

        LOG.debug(pprint.pprint(container_config))
        (state, data) = self.container_client.client('init', container_config=container_config,
                                                     host=host)
        self.container_client.client('wait', oid=data.get('operation').split('/')[3],
                                     host=host)

        if configdrive.required_by(instance):
            container_configdrive = (
                self.configure_container_configdrive(
                    container_config,
                    instance,
                    injected_files,
                    admin_password))
            LOG.debug(pprint.pprint(container_configdrive))
            self.container_client.client('update', instnace=name,
                                         container_config=container_configdrive,
                                         host=host)

        if rescue:
            container_rescue_devices = (
                self.configure_container_rescuedisk(
                    container_config,
                    instance))
            LOG.debug(pprint.pprint(container_rescue_devices))
            self.container_client.client('update', instnace=name,
                                         container_config=container_rescue_devices,
                                         host=host)

        return container_config

    def configure_container_config(self, name, container_config, instance):
        LOG.debug('Configure LXD container')

        ''' Set the limits. '''
        flavor = instance.flavor
        mem = flavor.memory_mb * units.Mi
        vcpus = flavor.vcpus

        container_config = self.add_config(container_config, 'name',
                                           name)
        container_config = self.add_config(container_config, 'profiles',
                                           [str(CONF.lxd.default_profile)])

        if mem >= 0:
            self.add_config(container_config, 'config', 'limits.memory',
                            data='%s' % mem)
        if vcpus >= 1:
            self.add_config(container_config, 'config', 'limits.cpus',
                            data='%s' % vcpus)

        ''' Basic container configuration. '''
        self.add_config(container_config, 'config', 'raw.lxc',
                        data='lxc.console.logfile=%s\n'
                        % self.container_dir.get_console_path(instance.uuid))
        return container_config

    def configure_lxd_image(self, container_config, instance, image_meta):
        LOG.debug('Getting LXD image')


        self.add_config(container_config, 'source',
                        {'type': 'image',
                         'alias': instance.image_ref
                         })
        return container_config

    def configure_network_devices(self, container_config,
                                  instance, network_info, host=None):
        LOG.debug('Get network devices')

        if not network_info:
            return 

        cfg = self.vif_driver.get_config(instance,
                                             network_info)

        container_network_devices = self.add_config(container_config, 
                                        'devices',cfg['bridge'],
                                        data={'nictype': 'bridged',
                                              'hwaddr': cfg['mac_address'],
                                              'parent': cfg['bridge'],
                                              'type': 'nic'})

        LOG.debug(pprint.pprint(container_config))
        self.container_client.client('update', instance=instance.uuid,
                                     container_config=container_network_devices,
                                     host=host)

        return container_config

    def configure_disk_path(self, container_config, vfs_type, instance):
        LOG.debug('Create disk path')
        config_drive = self.container_dir.get_container_configdrive(
            instance.uuid)
        self.add_config(container_config, 'devices', str(vfs_type),
                        data={'path': 'mnt',
                              'source': config_drive,
                              'type': 'disk'})
        return container_config

    def configure_container_rescuedisk(self, container_config, instance):
        LOG.debug('Create rescue disk')
        rescue_path = self.container_dir.get_container_rootfs(instance.uuid)
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
        name = instance.uuid
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

    def configure_container_net_device(self, instance, vif):
        LOG.debug('Configure container device')
        container_config = self._get_container_config(instance, vif)
        bridge = 'qbr%s' % vif['id'][:11]

        container_config = self.add_config(
            container_config, 'devices',
            bridge,
            data={'name': self._get_network_device(instance.uuid),
                  'nictype': 'bridged',
                  'hwaddr': vif['address'],
                  'parent': bridge,
                  'type': 'nic'})
        return container_config

    def _get_container_config(self, instance, network_info, host=None):
        container_update = self._init_container_config()

        container_old = self.container_client.client('config', instance=instance.uuid,
                                                      host=host)
        container_config = self._convert(container_old['config'])
        container_devices = self._convert(container_old['devices'])

        container_update['config'] = container_config
        container_update['devices'] = container_devices

        LOG.debug(pprint.pprint(container_update))

        return container_update

    def _get_network_device(self, instance, host=None):
        data = self.container_client.client('info', instance=instance, host=None)
        lines = open('/proc/%s/net/dev' % data['init']).readlines()
        interfaces = []
        for line in lines[2:]:
            if line.find(':') < 0:
                continue
            face, _ = line.split(':')
            if 'eth' in face:
                interfaces.append(face.strip())

        if len(interfaces) == 1:
            return 'eth1'
        else:
            return 'eth%s' % int(len(interfaces) - 1)

    def _convert(self, data):
        if isinstance(data, six.string_types):
            return str(data)
        elif isinstance(data, collections.Mapping):
            return dict(map(self._convert, data.items()))
        elif isinstance(data, collections.Iterable):
            return type(data)(map(self._convert, data))
        else:
            return data

    def add_config(self, config, key, value, data=None):
        if key == 'config':
            config.setdefault('config', {}).setdefault(value, data)
        elif key == 'devices':
            config.setdefault('devices', {}).setdefault(value, data)
        elif key not in config:
            config.setdefault(key, value)
        return config
