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

from oslo_config import cfg
from oslo_utils import fileutils
from nova import exception
from nova import i18n
from nova import utils
from nova.virt import driver

from nova.virt.lxd import common

_ = i18n._
CONF = cfg.CONF


def attach_ephemeral(client, block_device_info, lxd_config, instance):
    """Attach ephemeral storage to an instance."""
    ephemeral_storage = driver.block_device_info_get_ephemerals(
        block_device_info)
    if ephemeral_storage:
        storage_driver = lxd_config['environment']['storage']

        container = client.containers.get(instance.name)
        container_id_map = container.config[
            'volatile.last_state.idmap'].split(',')
        storage_id = container_id_map[2].split(':')[1]

        instance_attrs = common.InstanceAttributes(instance)
        for ephemeral in ephemeral_storage:
            storage_dir = os.path.join(
                instance_attrs.storage_path, ephemeral['virtual_name'])
            if storage_driver == 'zfs':
                # NOTE(ajkavanagh) - BUG/1782329 - this is temporary until
                # storage pools is implemented.  LXD 3 removed the
                # storage.zfs_pool_name key from the config.  So, if it fails,
                # we need to grab the configured storage pool and use that as
                # the name instead.
                try:
                    zfs_pool = lxd_config['config']['storage.zfs_pool_name']
                except KeyError:
                    zfs_pool = CONF.lxd.pool

                utils.execute(
                    'zfs', 'create',
                    '-o', 'mountpoint=%s' % storage_dir,
                    '-o', 'quota=%sG' % instance.ephemeral_gb,
                          '%s/%s-ephemeral' % (zfs_pool, instance.name),
                    run_as_root=True)
            elif storage_driver == 'btrfs':
                # We re-use the same btrfs subvolumes that LXD uses,
                # so the ephemeral storage path is updated in the profile
                # before the container starts.
                storage_dir = os.path.join(
                    instance_attrs.container_path, ephemeral['virtual_name'])
                profile = client.profiles.get(instance.name)
                storage_name = ephemeral['virtual_name']
                profile.devices[storage_name]['source'] = storage_dir
                profile.save()

                utils.execute(
                    'btrfs', 'subvolume', 'create', storage_dir,
                    run_as_root=True)
                utils.execute(
                    'btrfs', 'qgroup', 'limit',
                    '%sg' % instance.ephemeral_gb, storage_dir,
                    run_as_root=True)
            elif storage_driver == 'lvm':
                fileutils.ensure_tree(storage_dir)

                lvm_pool = lxd_config['config']['storage.lvm_vg_name']
                lvm_volume = '%s-%s' % (instance.name,
                                        ephemeral['virtual_name'])
                lvm_path = '/dev/%s/%s' % (lvm_pool, lvm_volume)

                cmd = (
                    'lvcreate', '-L', '%sG' % instance.ephemeral_gb,
                    '-n', lvm_volume, lvm_pool)
                utils.execute(*cmd, run_as_root=True, attempts=3)

                utils.execute('mkfs', '-t', 'ext4',
                              lvm_path, run_as_root=True)
                cmd = ('mount', '-t', 'ext4', lvm_path, storage_dir)
                utils.execute(*cmd, run_as_root=True)
            else:
                reason = _("Unsupport LXD storage detected. Supported"
                           " storage drivers are zfs and btrfs.")
                raise exception.NovaException(reason)

            utils.execute(
                'chown', storage_id,
                storage_dir, run_as_root=True)


def detach_ephemeral(client, block_device_info, lxd_config, instance):
    """Detach ephemeral device from the instance."""
    ephemeral_storage = driver.block_device_info_get_ephemerals(
        block_device_info)
    if ephemeral_storage:
        storage_driver = lxd_config['environment']['storage']

        for ephemeral in ephemeral_storage:
            if storage_driver == 'zfs':
                # NOTE(ajkavanagh) - BUG/1782329 - this is temporary until
                # storage pools is implemented.  LXD 3 removed the
                # storage.zfs_pool_name key from the config.  So, if it fails,
                # we need to grab the configured storage pool and use that as
                # the name instead.
                try:
                    zfs_pool = lxd_config['config']['storage.zfs_pool_name']
                except KeyError:
                    zfs_pool = CONF.lxd.pool

                utils.execute(
                    'zfs', 'destroy',
                    '%s/%s-ephemeral' % (zfs_pool, instance.name),
                    run_as_root=True)
            if storage_driver == 'lvm':
                lvm_pool = lxd_config['config']['storage.lvm_vg_name']

                lvm_path = '/dev/%s/%s-%s' % (
                    lvm_pool, instance.name, ephemeral['virtual_name'])

                utils.execute('umount', lvm_path, run_as_root=True)
                utils.execute('lvremove', '-f', lvm_path, run_as_root=True)
