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

""" Storage driver for nova-lxd """

from oslo_log import log as logging
from oslo_utils import fileutils
import os
import shutil

import nova.conf
from nova import i18n
from nova import exception
from nova import utils

from nova.virt.lxd import utils as container_utils
from nova.virt.lxd import volumeops
from nova.virt.lxd.storage import storage

_ = i18n._

LOG = logging.getLogger(__name__)

CONF = nova.conf.CONF


class LXDFSStorageDriver(storage.LXDStorageDriver):
    """FS Storage Driver."""
    def create_storage(self, block_device_info, instance):
        """Create the required storage for the instance.

        :param block_device_info: nova block device dict
        :param instance: nova instance object
        """
        LOG.debug('create_storage called for instance', instance=instance)
        ephemeral_config = volumeops.ensure_ephemeral(
            block_device_info, instance)
        if ephemeral_config:
            owner_uid = int(container_utils.uid_map(
                '/etc/subuid')) + os.getuid()
            storage_dir = ephemeral_config['src_dir']
            fileutils.ensure_tree(storage_dir)
            utils.execute(
                'chown', '-R', '%s:%s' % (owner_uid,
                                          owner_uid),
                storage_dir, run_as_root=True)

    def remove_storage(self, block_device_info, instance):
        """Remove the required storage for the instance.

        :param block_device_info: instance block device dict
        :param instance: nova instance object
        """
        LOG.debug('remove_storage called for instance', instance=instance)
        ephemeral_config = volumeops.ensure_ephemeral(
            block_device_info, instance)
        if ephemeral_config:
            storage_dir = ephemeral_config['src_dir']
            utils.execute(
                'chown', '-R', '%s:%s' % (os.getuid(), os.getuid()),
                storage_dir, run_as_root=True)
            shutil.rmtree(storage_dir)

    def resize_storage(self, block_device_info, instance):
        """Resize thre required storage

        :param block_device_info: isntance block information
        :param instanace: nova instnace object
        """
        LOG.debug('resize_storage called for instance', instance=instance)
        reason = _('Resize not supported for LXDFSStorageDriver')
        raise exception.CannotResizeDisk(reason)
