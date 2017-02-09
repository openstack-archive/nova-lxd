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

import socket

from nova import exception
from nova import i18n
from nova.virt import configdrive

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils

from nova_lxd.nova.virt.lxd import session
from nova_lxd.nova.virt.lxd import utils as container_dir
from nova_lxd.nova.virt.lxd import vif

_ = i18n._
_LE = i18n._LE
_LI = i18n._LI

CONF = cfg.CONF
CONF.import_opt('my_ip', 'nova.netconf')
LOG = logging.getLogger(__name__)


class LXDContainerConfig(object):
    """LXD configuration methods."""

    def __init__(self):
        self.container_dir = container_dir.LXDContainerDirectories()
        self.session = session.LXDAPISession()
        self.vif_driver = vif.LXDGenericDriver()

    def create_container(self, instance):
        """Create a LXD container dictionary so that we can
           use it to initialize a container

           :param instance: nova instance object
        """
        LOG.debug('create_container called for instance', instance=instance)

        instance_name = instance.name
        try:

            # Fetch the container configuration from the current nova
            # instance object
            container_config = {
                'name': instance_name,
                'profiles': [str(instance.name)],
                'source': self.get_container_source(instance),
                'devices': {}
            }

            # if a configdrive is required, setup the mount point for
            # the container
            if configdrive.required_by(instance):
                configdrive_dir = \
                    self.container_dir.get_container_configdrive(
                        instance.name)
                config = self.configure_disk_path(configdrive_dir,
                                                  'var/lib/cloud/data',
                                                  'configdrive', instance)
                container_config['devices'].update(config)

            if container_config is None:
                msg = _('Failed to get container configuration for %s') \
                    % instance_name
                raise exception.NovaException(msg)
            return container_config
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error('Failed to get container configuration'
                          ' %(instance)s: %(ex)s',
                          {'instance': instance_name, 'ex': ex},
                          instance=instance)

    def create_profile(self, instance, network_info):
        """Create a LXD container profile configuration

        :param instance: nova instance object
        :param network_info: nova network configuration object
        :return: LXD container profile dictionary
        """
        LOG.debug('create_container_profile called for instance',
                  instance=instance)
        instance_name = instance.name
        try:
            config = {}
            config['name'] = str(instance_name)
            config['config'] = self.create_config(instance_name, instance)

            # Restrict the size of the "/" disk
            config['devices'] = self.configure_container_root(instance)

            if network_info:
                config['devices'].update(self.create_network(instance_name,
                                                             instance,
                                                             network_info))

            return config
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(
                    _LE('Failed to create profile %(instance)s: %(ex)s'),
                    {'instance': instance_name, 'ex': ex}, instance=instance)

    def create_config(self, instance_name, instance):
        """Create the LXD container resources

        :param instance_name: instance name
        :param instance: nova instance object
        :return: LXD resources dictionary
        """
        LOG.debug('create_config called for instance', instance=instance)
        try:
            config = {}

            # Update continaer options
            config.update(self.config_instance_options(config, instance))

            # Set the instance memory limit
            mem = instance.memory_mb
            if mem >= 0:
                config['limits.memory'] = '%sMB' % mem

            # Set the instance vcpu limit
            vcpus = instance.flavor.vcpus
            if vcpus >= 0:
                config['limits.cpu'] = str(vcpus)

            # Configure the console for the instance
            config['raw.lxc'] = 'lxc.console.logfile=%s\n' \
                % self.container_dir.get_console_path(instance_name)

            return config
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(
                    _LE('Failed to set container resources %(instance)s: '
                        '%(ex)s'), {'instance': instance_name, 'ex': ex},
                    instance=instance)

    def config_instance_options(self, config, instance):
        LOG.debug('config_instance_options called for instance',
                  instance=instance)

        # Set the container to autostart when the host reboots
        config['boot.autostart'] = 'True'
        config['environment.product_name'] = 'OpenStack Nova'

        # Determine if we require a nested container
        flavor = instance.flavor
        lxd_nested_allowed = flavor.extra_specs.get(
            'lxd:nested_allowed', False)
        if lxd_nested_allowed:
            config['security.nesting'] = 'True'

        # Determine if we require a privileged container
        lxd_privileged_allowed = flavor.extra_specs.get(
            'lxd:privileged_allowed', False)
        if lxd_privileged_allowed:
            config['security.privileged'] = 'True'

        lxd_isolated = flavor.extra_specs.get(
            'lxd:isolated', False)
        if lxd_isolated:
            extensions = self.session.get_host_extensions()
            if 'id_map' in extensions:
                config['security.idmap.isolated'] = 'True'
            else:
                msg = _('Host does not support isolated instances')
                raise exception.NovaException(msg)

        return config

    def configure_container_root(self, instance):
        LOG.debug('configure_container_root called for instance',
                  instance=instance)
        try:
            config = {}
            lxd_config = self.session.get_host_config(instance)
            if str(lxd_config['storage']) in ['btrfs', 'zfs']:
                config['root'] = {'path': '/',
                                  'type': 'disk',
                                  'size': '%sGB' % str(instance.root_gb)}
            else:
                config['root'] = {'path': '/',
                                  'type': 'disk'}
            return config
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Failed to configure disk for '
                              '%(instance)s: %(ex)s'),
                          {'instance': instance.name, 'ex': ex},
                          instance=instance)

    def create_network(self, instance_name, instance, network_info):
        """Create the LXD container network on the host

        :param instance_name: nova instance name
        :param instance: nova instance object
        :param network_info: instance network configuration object
        :return:network configuration dictionary
        """
        LOG.debug('create_network called for instance', instance=instance)
        try:
            network_devices = {}

            if not network_info:
                return

            for vifaddr in network_info:
                cfg = self.vif_driver.get_config(instance, vifaddr)
                key = str(cfg['bridge'])
                network_devices[key] = \
                    {'nictype': 'bridged',
                     'hwaddr': str(cfg['mac_address']),
                     'parent': key,
                     'type': 'nic'}
                host_device = self.vif_driver.get_vif_devname(vifaddr)
                if host_device:
                    network_devices[key]['host_name'] = host_device
                return network_devices
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(
                    _LE('Fail to configure network for %(instance)s: %(ex)s'),
                    {'instance': instance_name, 'ex': ex}, instance=instance)

    def get_container_source(self, instance):
        """Set the LXD container image for the instance.

        :param instance: nova instance object
        :return: the container source
        """
        LOG.debug('get_container_source called for instance',
                  instance=instance)
        try:
            container_source = {'type': 'image',
                                'alias': str(instance.image_ref)}
            if container_source is None:
                msg = _('Failed to determine container source for %s') \
                    % instance.name
                raise exception.NovaException(msg)
            return container_source
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(
                    _LE('Failed to configure container source '
                        '%(instance)s: %(ex)s'),
                    {'instance': instance.name, 'ex': ex},
                    instance=instance)

    def get_container_migrate(self, container_migrate, migration,
                              host, instance):
        LOG.debug('get_container_migrate called for instance',
                  instance=instance)
        try:
            # Generate the container config
            host = socket.gethostbyname(host)
            container_metadata = container_migrate['metadata']
            container_control = container_metadata['metadata']['control']
            container_fs = container_metadata['metadata']['fs']

            container_url = 'https://%s:8443%s' \
                % (host, container_migrate.get('operation'))

            container_migrate = {
                'base_image': '',
                'mode': 'pull',
                'certificate': str(self.session.host_certificate(instance,
                                                                 host)),
                'operation': str(container_url),
                'secrets': {
                        'control': str(container_control),
                        'fs': str(container_fs)
                },
                'type': 'migration'
            }

            return container_migrate
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Failed to configure migation source '
                              '%(instance)s: %(ex)s'),
                          {'instance': instance.name, 'ex': ex},
                          instance=instance)

    def configure_disk_path(self, src_path, dest_path, vfs_type, instance):
        """Configure the host mount point for the LXD container

        :param src_path: source path on the house
        :param dest_path: destination path on the LXD container
        :param vfs_type: dictionary identifier
        :param instance: nova instance object
        :return: container disk paths
        """
        LOG.debug('configure_disk_path called for instance',
                  instance=instance)
        try:
            config = {}
            config[vfs_type] = {'path': dest_path,
                                'source': src_path,
                                'type': 'disk',
                                'optional': 'True'}
            return config
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Failed to configure disk for '
                              '%(instance)s: %(ex)s'),
                          {'instance': instance.name, 'ex': ex},
                          instance=instance)

    def create_container_net_device(self, instance, vif):
        """Translate nova network object into a LXD interface

        :param instance: nova instance object
        :param vif: network instaance object
        """
        LOG.debug('create_container_net_device called for instance',
                  insance=instance)
        try:
            network_config = self.vif_driver.get_config(instance, vif)

            config = {}
            config[self.get_network_device(instance)] = {
                'nictype': 'bridged',
                'hwaddr': str(vif['address']),
                'parent': str(network_config['bridge']),
                'type': 'nic'}

            return config
        except Exception as ex:
            LOG.error(_LE('Failed to configure network for '
                          '%(instance)s: %(ex)s'),
                      {'instance': instance.name, 'ex': ex},
                      instance=instance)

    def get_network_device(self, instance):
        """Try to detect which network interfaces are available in a contianer

        :param instance: nova instance object
        """
        LOG.debug('get_network_device called for instance', instance=instance)
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
