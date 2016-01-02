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
from nova.api.metadata import base as instance_metadata
from nova import exception
from nova import i18n
from nova.virt import configdrive
from nova.virt import driver
import os
import pprint

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import fileutils
from oslo_utils import units
import six

from nova_lxd.nova.virt.lxd.session import session
from nova_lxd.nova.virt.lxd import utils as container_dir
from nova_lxd.nova.virt.lxd import vif

_ = i18n._
_LE = i18n._LE
_LI = i18n._LI

CONF = cfg.CONF
CONF.import_opt('my_ip', 'nova.netconf')
LOG = logging.getLogger(__name__)


class LXDContainerConfig(object):

    def __init__(self):
        self.container_dir = container_dir.LXDContainerDirectories()
        self.session = session.LXDAPISession()
        self.vif_driver = vif.LXDGenericDriver()

    def _init_container_config(self):
        config = {}
        config.setdefault('config', {})
        config.setdefault('devices', {})
        return config

    def create_container(self, instance, injected_files,
                         block_device_info, rescue):
        LOG.debug('Creating container config')

        # Ensure the directory exists and is writable
        fileutils.ensure_tree(
            self.container_dir.get_instance_dir(instance.name))

        # Check to see if we are using swap.
        swap = driver.block_device_info_get_swap(block_device_info)
        if driver.swap_is_usable(swap):
            msg = _('Swap space is not supported by LXD.')
            raise exception.NovaException(msg)

        # Check to see if ephemeral block devices exist.
        ephemeral_gb = instance.ephemeral_gb
        if ephemeral_gb > 0:
            msg = _('Ephemeral block devices are not supported by LXD.')
            raise exception.NovaException(msg)

        container_config = self._init_container_config()
        container_config = self.add_config(container_config, 'name',
                                           instance.name)
        container_config = self.add_config(container_config, 'profiles',
                                           [str(CONF.lxd.default_profile)])
        container_config = self.configure_container_config(container_config,
                                                           instance)

        ''' Create an LXD image '''
        container_config = (
            self.add_config(container_config, 'source',
                            self.configure_lxd_image(container_config,
                                                     instance)))

        if configdrive.required_by(instance):
            container_configdrive = (
                self.configure_container_configdrive(
                    container_config,
                    instance,
                    injected_files))
            LOG.debug(pprint.pprint(container_configdrive))

        if rescue:
            container_rescue_devices = (
                self.configure_container_rescuedisk(
                    container_config,
                    instance))
            LOG.debug(pprint.pprint(container_rescue_devices))

        return container_config

    def configure_container_config(self, container_config, instance):
        LOG.debug('Configure LXD container config')

        ''' Set the limits. '''
        flavor = instance.flavor
        mem = flavor.memory_mb * units.Mi

        if mem >= 0:
            self.add_config(container_config, 'config', 'limits.memory',
                            data='%s' % mem)

        ''' Basic container configuration. '''
        self.add_config(container_config, 'config', 'raw.lxc',
                        data='lxc.console.logfile=%s\n'
                        % self.container_dir.get_console_path(instance.name))
        return container_config

    def configure_lxd_image(self, container_config, instance):
        LOG.debug('Getting LXD image source')

        self.add_config(container_config, 'source',
                        {'type': 'image',
                         'alias': instance.image_ref
                         })
        return container_config

    def configure_network_devices(self, container_config,
                                  instance, network_info):
        LOG.debug('Configure LXD network device')

        if not network_info:
            return

        cfg = self.vif_driver.get_config(instance,
                                         network_info)

        network_devices = self.add_config(container_config,
                                          'devices', cfg['bridge'],
                                          data={'nictype': 'bridged',
                                                'hwaddr': cfg['mac_address'],
                                                'parent': cfg['bridge'],
                                                'type': 'nic'})

        LOG.debug(pprint.pprint(container_config))
        self.session.container_update(network_devices, instance)

        return container_config

    def configure_disk_path(self, container_config, vfs_type, instance):
        LOG.debug('Creating LXD disk path')
        config_drive = self.container_dir.get_container_configdrive(
            instance.name)
        self.add_config(container_config, 'devices', str(vfs_type),
                        data={'path': 'mnt',
                              'source': config_drive,
                              'type': 'disk'})
        return container_config

    def configure_container_rescuedisk(self, container_config, instance):
        LOG.debug('Creating LXD rescue disk')
        instance_name = '%s-backup' % instance.name

        if self.container_dir.is_lvm(instance_name):
            self.session.mount_filesystem(
                self.container_dir.get_container_lvm(instance_name),
                (os.path.join(self.container_dir.get_container_dir(
                    instance), instance_name)))

        rescue_path = self.container_dir.get_container_rescue(instance_name)
        self.add_config(container_config, 'devices', 'rescue',
                        data={'path': 'mnt',
                              'source': rescue_path,
                              'type': 'disk'})
        return container_config

    def configure_container_configdrive(self, container_config, instance,
                                        injected_files):
        LOG.debug('Creating LXD config drive')
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

    def configure_container_net_device(self, instance, vif):
        LOG.debug('Configure LXD network device')
        container_config = self.get_container_config(instance)

        container_network_config = self.vif_driver.get_config(instance, vif)

        container_config = self.add_config(
            container_config, 'devices',
            container_network_config['bridge'],
            data={'name': self._get_network_device(instance.name),
                  'nictype': 'bridged',
                  'hwaddr': vif['address'],
                  'parent': container_network_config['bridge'],
                  'type': 'nic'})
        return container_config

    def configure_container_migrate(self, instance, container_ws, host):
        LOG.debug('Creating container config for migration.')
        container_config = self.get_container_config(instance, host=host)

        container_config = self.add_config(container_config, 'source',
                                           self.configure_lxd_ws(
                                               container_config,
                                               container_ws,
                                               host))

        return container_config

    def configure_lxd_ws(self, container_config, container_ws, host):
        container_url = ('wss://%s:8443/1.0/operations/%s/websocket'
                         % (host, container_ws['operation']))
        container_migrate = {'base-image': '',
                             "mode": "pull",
                             "operation": container_url,
                             "secrets": {
                                 "control": container_ws['control'],
                                 "fs": container_ws['fs']
                             },
                             "type": "migration"}

        container_config = (self.add_config(container_config, 'source',
                                            container_migrate))
        return container_config

    def get_container_config(self, instance, host=None):
        LOG.debug('Fetching LXD configuration')
        container_update = self._init_container_config()

        if host is None:
            host = instance.host

        container_old = self.session.container_config(instance)

        container_config = self._convert(container_old['config'])
        container_devices = self._convert(container_old['devices'])

        container_update['name'] = instance.name
        container_update['profiles'] = [str(CONF.lxd.default_profile)]
        container_update['config'] = container_config
        container_update['devices'] = container_devices

        return container_update

    def _get_network_device(self, instance):
        data = self.session.container_info(instance)
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
