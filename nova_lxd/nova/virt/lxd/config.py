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

from nova import exception
from nova import i18n
from nova.virt import configdrive

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils

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

    def create_container(self, instance, rescue=False):
        """Create a LXD contaienr dictionary so that we can
           use it to initialize a container

           :param instance: nova instance object
           :param rescue: boolean to create a rescue container,
                          True if rescue container, False otherwise
        """
        LOG.debug('create_container called for instance', instance=instance)

        try:
            instance_name = instance.name
            if rescue:
                instance_name = '%s-rescue' % instance.name

            # Fetch the container configuration from the current nova
            # instance object
            container_config = self.get_container_config(instance, rescue)
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

    def create_profile(self, instance, network_info, rescue):
        """Create a LXD container profile configuration

        :param instance: nova instance object
        :param network_info: nova network configuration object
        :param rescue: boolean for rescue container
        :return: LXD container profile dictionary
        """
        LOG.debug('create_container_profile called for instance',
                  instance=instance)
        try:
            instance_name = instance.name
            if rescue:
                instance_name = '%s-rescue' % instance.name

            config = dict()
            config['name'] = str(instance_name)
            config['config'] = self._create_config(instance_name, instance)
            config['devices'] = self._create_network(instance_name, instance,
                                                     network_info)
            self.session.profile_create(config, instance)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(
                    _LE('Failed to create profile %(instance)s: %(ex)s'),
                    {'isntance': instance_name, 'ex': ex}, instance=instance)

    def _create_config(self, instance_name, instance):
        """Create the LXD container resources

        :param instance_name: instance name
        :param instance: nova instance object
        :return: LXD resources dictionary
        """
        LOG.debug('_create_config called for instance', instance=instance)
        try:
            config = dict()

            mem = instance.memory_mb
            if mem >= 0:
                config['limits.memory'] = '%sMB' % mem

            config['raw.lxc'] = 'lxc.console.logfile=%s\n' \
                % self.container_dir.get_console_path(instance_name)

            return config
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(
                    _LE('Failed to set container resources %(instance)s: '
                        '%(ex)s'), {'instance': instance_name, 'ex': ex},
                    instance=instance)

    def _create_network(self, instance_name, instance, network_info):
        """Create the LXD container network on the host

        :param instance_name: nova instance name
        :param instance: nova instance object
        :param network_info: instance network configuration object
        :return:network configuration dictionary
        """
        LOG.debug('_create_network called for instance', instance=instance)
        try:
            network_devices = dict()

            for vifaddr in network_info:
                cfg = self.vif_driver.get_config(instance, vifaddr)
                network_devices[str(cfg['bridge'])] = \
                    {'nictype': 'bridged',
                     'hwaddr': str(cfg['mac_address']),
                     'parent': str(cfg['bridge']),
                     'type': 'nic'}
                return network_devices
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(
                    _LE('Fail to configure network for %(instance)s: %(ex)s'),
                    {'instance': instance_name, 'ex': ex}, instance=instance)

    def get_container_config(self, instance, rescue):
        """Translate the nova instance object into an LXD configuration
           dictionary.

           :param instance nova instance object
           :param rescue: boolean to create rescue containers or not.
         """
        LOG.debug('get_container_config called for instance',
                  instance=instance)
        try:
            instance_name = instance.name
            if rescue:
                instance_name = '%s-rescue' % instance.name

            container_config = dict(name=instance_name,
                                    profiles=[str(instance_name)],
                                    source=self._get_container_source(
                                        instance),
                                    devices={})
            # if a config drive is required setup the mount point for the
            # container
            if configdrive.required_by(instance):
                configdrive_dir = \
                    self.container_dir.get_container_configdrive(
                        instance_name)
                config = self._configure_disk_path(configdrive_dir, 'mnt',
                                                   'configdrive', instance)
                container_config['devices'].update(config)

            # if a rescue container is required, setupt the mount point for
            #  the container
            if rescue:
                rescue_dir = self.container_dir.get_container_rescue(
                    instance_name)
                config = self._configure_disk_path(rescue_dir, 'mnt',
                                                   'rescue', instance)
                container_config['devices'].update(config)

            return container_config
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Failed to translate nova object '
                              'for %(instance)s: %(ex)'),
                          {'instance': instance_name, 'ex': ex},
                          instance=instance)

    def _get_container_source(self, instance):
        """Set the LXD container image for the instance.

        :param instance: nova instance object
        :return: the container source
        """
        LOG.debug('_get_container_source called for instance',
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

    def _configure_disk_path(self, src_path, dest_path, vfs_type, instance):
        """Configure the host mount piont for the LXD container

        :param src_path: source path on the house
        :param dest_path: destination path on the LXD container
        :param vfs_type: dictionary identifier
        :param instance: nova instance object
        :return: container disk paths
        """
        LOG.debug('_configure_disk_path called for instance',
                  instance=instance)
        try:
            config = {}
            config[vfs_type] = {'path': src_path,
                                'source': dest_path,
                                'type': 'disk'}
            return config
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Failed to configure disk for '
                              '%(instance)s: %(ex)s'),
                          {'instance': instance.name, 'ex': ex},
                          instance=instance)
