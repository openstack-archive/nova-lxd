# Copyright (c) 2015 Canonical Ltd
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

from oslo_log import log as logging
from oslo_utils import fileutils

import nova.conf
from nova import exception
from nova import i18n
from nova import utils

from nova.virt.lxd import utils as container_utils

_ = i18n._
_LE = i18n._LE

CONF = nova.conf.CONF

LOG = logging.getLogger(__name__)


class LXDStorageDriver(object):

    def __init__(self, volume_driver):
        self.storage_driver = volume_driver
        self.storage_drivers = {'fs': LXDFSStorage()}

    def get_storage_driver(self):
        if self.storage_driver not in self.storage_drivers:
            msg = _('%s is not supported') % self.storage_driver
            raise exception.NovaException(msg)
        return self.storage_drivers[self.storage_driver]

    def create_storage(self, block_device_info, instance):
        LOG.debug('create_storage called for instance', instance=instance)

        storage_driver = self.get_storage_driver()
        storage_driver.create_storage(block_device_info, instance)

    def remove_storage(self, block_device_info, instance):
        LOG.debug('remove_storage called for instance', instance=instance)

        storage_driver = self.get_storage_driver()
        storage_driver.remove_storage(block_device_info, instance)

    def resize_storage(self, block_device_info, instance):
        LOG.debug('resize_storage called for instance', instance=instance)

        storage_driver = self.get_storage_driver()
        storage_driver.resize_storage(block_device_info, instance)


class LXDFSStorage(object):

    def create_storage(self, block_device_info, instance):
        if instance['ephemeral_gb'] != 0:
            ephemerals = block_device_info.get('ephemerals', [])

            root_dir = container_utils.get_container_rootfs(instance.name)
            if ephemerals == []:
                ephemeral_src = container_utils.get_container_storage(
                    ephemerals['virtual_name'], instance.name)
                fileutils.ensure_tree(ephemeral_src)
                utils.execute('chown',
                              os.stat(root_dir).st_uid,
                              ephemeral_src, run_as_root=True)
            else:
                for id, ephx in enumerate(ephemerals):
                    ephemeral_src = container_utils.get_container_storage(
                        ephx['virtual_name'], instance.name)
                    fileutils.ensure_tree(ephemeral_src)
                    utils.execute('chown',
                                  os.stat(root_dir).st_uid,
                                  ephemeral_src, run_as_root=True)

    def remove_storage(self, block_device_info, instance):
        pass

    def resize_storage(self):
        pass
