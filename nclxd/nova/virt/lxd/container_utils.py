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
import os

import container_client
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils


_ = i18n._
_LE = i18n._LE
_LW = i18n._LW
_LI = i18n._LI

CONF = cfg.CONF
LOG = logging.getLogger(__name__)


class LXDContainerUtils(object):

    def __init__(self):
        self.client = container_client.LXDContainerClient()

    def container_start(self, instance_name, instance):
        LOG.debug('Container start')
        try:
            (state, data) = self.client.client('start', instance=instance_name,
                                               host=instance.host)
            self.client.client('wait',
                               oid=data.get('operation').split('/')[3],
                               host=instance.host)
            LOG.info(_LI('Successfully started instance %s'),
                     instance_name, instance=instance)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(
                    _LE('Failed to start container %(instance)s: %(reason)s'),
                    {'instance': instance_name, 'reason': ex},
                    instance=instance)

    def container_stop(self, instance_name, host):
        LOG.debug('Container stop')
        try:
            (state, data) = (self.client.client('stop',
                                                instance=instance_name,
                                                host=host))
            self.client.client('wait',
                               oid=data.get('operation').split('/')[3],
                               host=host)
            LOG.info(_LI('Successfully stopped container %s'),
                     instance_name)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(
                    _LE('Failed to stop container %(instance)s: '
                        '%(reason)s'), {'instance': instance_name,
                                        'reason': ex})

    def container_reboot(self, instance):
        LOG.debug('Container reboot')
        try:
            (state, data) = self.client.client('reboot',
                                               instance=instance.uuid,
                                               host=instance.host)
            self.client.client('wait',
                               oid=data.get('operation').split('/')[3],
                               host=instance.host)
            LOG.info(_LI('Successfully rebooted container %s'),
                     instance.uuid, instance=instance)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(
                    _LE('Failed to reboot container %(instance)s: '
                        '%(reason)s'), {'instance': instance.uuid,
                                        'reason': ex}, instance=instance)

    def container_destroy(self, instance_name, host):
        LOG.debug('Container destroy')
        try:
            if not self.client.client(
                    'defined', instance=instance_name,
                    host=host):
                return

            self.container_stop(instance_name, host)

            (state, data) = self.client.client('destroy',
                                               instance=instance_name,
                                               host=host)
            self.client.client('wait',
                               oid=data.get('operation').split('/')[3],
                               host=host)
            LOG.info(_LI('Successfully destroyed container %s'),
                     instance_name)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Failed to destroy container %(instance)s: '
                              '%(reason)s'), {'instance': instance_name,
                                              'reason': ex})

    def container_pause(self, instance_name, instance):
        LOG.debug('Container pause')
        try:
            (state, data) = self.client.client('pause', instance=instance_name,
                                               host=instance.host)
            self.client.client('wait',
                               oid=data.get('operation').split('/')[3],
                               host=instance.host)
            LOG.info(_LI('Successfully paused container %s'),
                     instance.uuid, instance=instance)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(
                    _LE('Failed to pause container %(instance)s: '
                        '%(reason)s'),
                    {'instance': instance.uuid,
                     'reason': ex}, instance=instance)

    def container_unpause(self, instance_name, instance):
        LOG.debug('Container unpause')
        try:
            (state, data) = self.client.client('unpause',
                                               instance=instance_name,
                                               host=instance.host)
            self.client.client('wait',
                               oid=data.get('operation').split('/')[3],
                               host=instance.host)
            LOG.info(_LI('Successfully resumed container %s'),
                     instance.uuid, instance=instance)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(
                    _LE('Failed to unpause container %(instance)s: '
                        '%(reason)s'), {'instance': instance_name,
                                        'reason': ex})

    def container_snapshot(self, snapshot, instance):
        try:
            (state, data) = self.client.client('snapshot_create',
                                               instance=instance.uuid,
                                               container_snapshot=snapshot,
                                               host=instance.host)
            self.client.client('wait',
                               oid=data.get('operation').split('/')[3],
                               host=instance.host)
            LOG.info(_LI('Successfully snapshotted container %s'),
                     instance.uuid, instance=instance)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(
                    _LE('Failed to rename container %(instance)s: %(reason)s'),
                    {'instance': instance.uuid,
                     'reason': ex}, instance=instance)

    def container_copy(self, config, instance):
        LOG.debug('Copying container')
        try:
            (state, data) = self.client.client('local_copy',
                                               container_config=config,
                                               host=instance.host)
            self.client.client('wait',
                               oid=data.get('operation').split('/')[3],
                               host=instance.host)
            LOG.info(_LI('Successfully copied container %s'),
                     instance.uuid, instance=instance)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(
                    _LE('Failed to rename container %(instance): %(reason)s'),
                    {'instance': instance.uuid,
                     'reason': ex})

    def container_move(self, old_name, config, instance):
        LOG.debug('Renaming container')
        try:
            (state, data) = (self.client.client('local_move',
                                                instance=old_name,
                                                container_config=config,
                                                host=instance.host))
            self.client.client('wait',
                               oid=data.get('operation').split('/')[3],
                               host=instance.host)
            LOG.info(_LI('Successfully renamed container %s'),
                     instance.uuid, instance=instance)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(
                    _LE('Failed to rename container %(instance)s: %(reason)s'),
                    {'instance': instance.uuid,
                     'reason': ex}, instance=instance)

    def container_migrate(self, instance_name, instance):
        LOG.debug('Migrate contianer')
        try:
            return self.client.client('migrate',
                                      instance=instance_name,
                                      host=instance.host)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(
                    _LE('Failed to rename container %(instance): %(reason)s'),
                    {'instance': instance_name,
                     'reason': ex}, instance=instance)

    def container_init(self, config, instance, host):
        LOG.debug('Initializing container')
        try:
            (state, data) = self.client.client('init',
                                               container_config=config,
                                               host=host)

            operation = data.get('operation').split('/')[3]
            self.client.client('wait',
                               oid=operation,
                               host=instance.host)
            _, data = self.client.client('operation_info',
                                         oid=operation,
                                         host=instance.host)
            data = data.get('metadata')
            if data['status_code'] == 200:
                LOG.info(_LI('Successfully created container %(instance)'),
                         instance=instance)
            else:
                raise exception.NovaException(data['metadata'])

        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(
                    _LE('Failed to create container %(instance)s: %(reason)s'),
                    {'instance': instance.uuid,
                     'reason': ex}, instance=instance)


class LXDContainerDirectories(object):

    def __init__(self):
        self.base_dir = os.path.join(CONF.instances_path,
                                     CONF.image_cache_subdirectory_name)

    def get_base_dir(self):
        return self.base_dir

    def get_instance_dir(self, instance):
        return os.path.join(CONF.instances_path,
                            instance)

    def get_container_rootfs_image(self, image_meta):
        return os.path.join(self.base_dir,
                            '%s-rootfs.tar.gz' % image_meta.get('id'))

    def get_container_manifest_image(self, image_meta):
        return os.path.join(self.base_dir,
                            '%s-manifest.tar' % image_meta.get('id'))

    def get_container_metadata(self, image_meta):
        return os.path.join(self.base_dir,
                            '%s-lxd.tar.xz' % image_meta.get('id'))

    def get_container_rootfsImg(self, image_meta):
        return os.path.join(self.base_dir,
                            '%s-root.tar.gz' % image_meta.get('id'))

    def get_container_configdrive(self, instance):
        return os.path.join(CONF.instances_path,
                            instance,
                            'config-drive')

    def get_console_path(self, instance):
        return os.path.join(CONF.lxd.root_dir,
                            'containers',
                            instance,
                            'console.log')

    def get_container_dir(self, instance):
        return os.path.join(CONF.lxd.root_dir,
                            'containers',
                            instance)

    def get_container_rootfs(self, instance):
        return os.path.join(CONF.lxd.root_dir,
                            'containers',
                            instance,
                            'rootfs')

    def get_container_rescue(self, instance):
        return os.path.join(CONF.lxd.root_dir,
                            'containers',
                            '%s-backup' % instance,
                            'rootfs')
