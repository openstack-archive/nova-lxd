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

import nova.conf
from nova import i18n
from nova.virt import driver
from nova.virt import configdrive

from oslo_log import log as logging
from oslo_utils import importutils

from nova.virt.lxd import config as container_config
from nova.virt.lxd import session
from nova.virt.lxd import utils as container_dir


_ = i18n._
_LE = i18n._LE
_LI = i18n._LI

CONF = nova.conf.CONF
LOG = logging.getLogger(__name__)


def ensure_ephemeral(block_device_info, instance):
    """Translate the instance block device into a dictionary
       that can be manipulated by nova-lxd

    :param block_device_info: nova storage device
    :param instance: nova instance object
    :return:
    """
    LOG.debug('ensure_ephemeral called for instance', instance=instance)

    ephemerals = driver.block_device_info_get_ephemerals(block_device_info)
    ephemeral_config = {}
    ephemeral_dir = os.path.join(CONF.instances_path, instance.name,
                                 'storage')
    for idx, eph in enumerate(ephemerals):
        ephemeral_config.update({'size': eph['size'],
                                 'name': eph['virtual_name'],
                                 'src_dir': os.path.join(
            ephemeral_dir,
            eph['virtual_name']),
            'dest_dir': '/mnt'})

    # There may be block devices defined but bo ephemerals. In this case
    # we need to allocate an ephemeral disk if required
    if not ephemerals and instance.flavor.ephemeral_gb > 0:
        ephemeral_config.update({'size': instance.flavor.ephemeral_gb,
                                 'name': '%s-ephemeral' % instance.name,
                                 'src_dir': os.path.join(ephemeral_dir,
                                                         '%s-ephemeral'
                                                         % instance.name),
                                 'dest_dir': '/mnt'})
    return ephemeral_config


class LXDVolumeOps(object):
    """nova-lxd volume methods."""

    def __init__(self):
        self.container_config = container_config.LXDContainerConfig()
        self.container_dir = container_dir.LXDContainerDirectories()
        self.session = session.LXDAPISession()

        self.storage_driver = self._get_storage_driver()

    def _get_storage_driver(self):
        """Load the approiate object chosen by the storage_driver
            configuration option

        :return:  volume storage driver
        """
        if CONF.lxd.storage_driver == 'fs':
            LOG.debug('Using FS')
            return importutils.import_object(
                'nova.virt.lxd.storage.fs.LXDFSStorageDriver')

    def get_disk_mapping(self, instance, block_device_info):
        """Translated the nova-lxd block disks into LXD configuration

        :param instance:
        :param block_device_info:
        :return:
        """
        LOG.debug('_get_disk_mapping called for instance', instance=instance)
        mapping = {}

        mapping = self._get_container_root_disk(instance)
        if self.is_ephemeral(block_device_info, instance):
            ephemeral_config = self._get_container_ephemeral_disk(
                block_device_info, instance)
            mapping.update(ephemeral_config)

        if configdrive.required_by(instance):
            mapping.update(self._get_container_configdrive(instance))

        return mapping

    def _get_container_root_disk(self, instance):
        """Translate the nova instance object into
           LXD configuration.

        :param instance: nova instance object
        :return: LXD configuration dictionary
        """
        LOG.debug('_get_container_root_disk called for instance',
                  instance=instance)

        disk_config = {}
        lxd_config = self.session.get_host_config()
        disk_config['root'] = {'path': '/', 'type': 'disk'}
        if (instance.root_gb >= 0 and
                lxd_config['storage'] in ['btrfs', 'zfs', 'lvm']):
            disk_config['root'].update(
                {'size': '%sGB' % str(instance.root_gb)})
        return disk_config

    def _get_container_ephemeral_disk(self, block_device_info, instance):
        """Translate the nova block device object into
           LXD configuration.

        :param instance: nova instance object
        :param: instance block device
        :return: LXD configuration dictionary
        """
        LOG.debug('_get_container_ephemeral_disk called for instance',
                  instance=instance)
        disk_config = {}
        ephemeral_config = ensure_ephemeral(block_device_info, instance)
        disk_config[str(ephemeral_config['name'])] = \
            {'type': 'disk',
             'path': ephemeral_config['dest_dir'],
             'source': ephemeral_config['src_dir'],
             }
        return disk_config

    def _get_container_configdrive(self, instance):
        """Translate the nova instance object into a
           LXD configuration

        :param instance: nova instance object
        :return: LXD configration dictionary
        """
        LOG.debug('_get_container_configdrive called for instnace',
                  instance=instance)
        configdrive_dir = \
            self.container_dir.get_container_configdrive(instance.name)
        config_drive = self.container_config.configure_disk_path(
            configdrive_dir, 'var/lib/cloud/data',
            'configdrive', instance)
        return config_drive

    def create_storage(self, block_device_info, instance):
        """Create the required storage on the compute host.

        :param block_device_info: instance block device information
        :param instance: nova instance object
        """
        LOG.debug('_create_ephemeral called for intsance', instance=instance)
        self.storage_driver.create_storage(block_device_info, instance)

    def remove_storage(self, block_device_info, instance):
        """Remove block storage from the compute host

        :param block_device_info: instance block device information
        :param instance: nova instance object
        """
        LOG.debug('_remove_storage called for instance', instance=instance)
        self.storage_driver.remove_storage(block_device_info, instance)

    def is_ephemeral(self, block_device_info, instance):
        """Check if ephemeral devices need to be created

        :param block_device_info: instnace block device
        :param instance: nova instance object
        :return: True if ephemerals are needed otherwise False
        """
        LOG.debug('is_ephemeral called for instance', instance=instance)
        if 'name' not in ensure_ephemeral(block_device_info, instance):
            return False
        return True
