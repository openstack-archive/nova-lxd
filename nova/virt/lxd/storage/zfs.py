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
from nova import utils

from oslo_concurrency import processutils
from oslo_log import log as logging
from oslo_utils import excutils

from nova.virt.lxd import utils as container_utils

_ = i18n._
_LE = i18n._LE
_LI = i18n._LI

CONF = nova.conf.CONF
LOG = logging.getLogger(__name__)


def create_storage(storage, instance, lxd_config):
    """Create a ZFS share and enable quotas for zfs share.

    :param storage: instance storage storage
    :param instance: nova instance object
    :param lxd_config: LXD server configuration
    """
    LOG.debug('create_storage called for instnace', instance=instance)

    try:
        root_dir = container_utils.get_container_rootfs(instance.name)
        storage_dir = container_utils.get_container_storage(
            storage['virtual_name'], instance.name)

        zfs_pool = str(lxd_config['config']['storage.zfs_pool_name'])
        utils.execute('zfs', 'create', '-o', 'quota=%sG' % instance.ephemeral_gb,
                      '%s/%s-storage' % (zfs_pool, instance.name),
                      run_as_root=True)
        utils.execute('zfs', 'set', 'mountpoint=%s' % storage_dir,
                      '%s/%s-storage' % (zfs_pool, instance.name),
                      run_as_root=True)
        utils.execute('chown', os.stat(root_dir).st_uid,
                      storage_dir, run_as_root=True)
    except processutils.ProcessExecutionError:
        with excutils.save_and_reraise_exception():
            LOG.error(_LE('Unable to create zfs share'))


def remove_storage(storage, instance, lxd_config):
    """Remove a ZFS share for a block storage

    :param storage: instace storage information
    :apram lxd_config: LXD host confiugration
    """
    LOG.debug('remove_storage called for instance', instance=instance)

    try:
        zfs_pool = str(lxd_config['config']['storage.zfs_pool_name'])
        storage_dir = container_utils.get_container_storage(
            storage['virtual_name'], instance.name)

        # Umount the share before trying to delete it otherwise
        # an exception will be thrown.
        utils.execute('umount', storage_dir, run_as_root=True)

        utils.execute(
            'zfs', 'destroy',
            '%s/%s-storage' % (zfs_pool, instance.name),
            run_as_root=True)
    except processutils.ProcessExecutionError:
        with excutils.save_and_reraise_exception():
            LOG.error(_LE('Unable to remove zfs share'))
