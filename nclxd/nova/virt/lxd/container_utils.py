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

import os

import time

from eventlet import greenthread

from oslo_config import cfg
from oslo_log import log as logging
from oslo_service import loopingcall
from oslo_utils import excutils

from nova import exception
from nova import i18n
from nova.compute import power_state
from nova.compute import task_states
from nova.compute import vm_states

import container_client

_ = i18n._
_LE = i18n._LE
_LW = i18n._LW
_LI = i18n._LI

CONF = cfg.CONF
LOG = logging.getLogger(__name__)


class LXDContainerUtils(object):

    def __init__(self):
        self.container_client = container_client.LXDContainerClient()

    def container_start(self, instance_name, instance):
        LOG.debug('Container start')
        try:
            (state, data) = self.container_client.client('start', instance=instance_name,
                                                             host=instance.host)
            timer = loopingcall.FixedIntervalLoopingCall(
                     self._wait_for_state,
                     data.get('operation').split('/')[3],
                     instance, power_state.RUNNING)
            timer.start(interval=CONF.lxd.retry_interval).wait()
            LOG.info(_LI('Succesfully started instance %s'),
                instance.uuid, instance=instance)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Failed to start container %(instance)s: %(reason)s'),
                    {'instance': instance.uuid, 'reason': ex}, instance=instance)

    def container_stop(self, instance_name, instance):
        LOG.debug('Container stop')
        try:
            (state, data) = self.container_client.client('stop', instance=instance_name,
                                                             host=instance.host)
            timer = loopingcall.FixedIntervalLoopingCall(
                        self._wait_for_state,
                        data.get('operation').split('/')[3],
                        instance, power_state.SHUTDOWN)
            timer.start(interval=CONF.lxd.retry_interval).wait()
            LOG.info(_LI('Succesfully stopped container %s'),
                     instance.uuid, instance=instance)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Failed to stop container %(instance)s: %(reason)s'),
                    {'instance': instance.uuid, 'reason': ex})

    def container_reboot(self, instance_name,  instance):
        LOG.debug('Container reboot')
        try:
            (state, data) = self.container_client.client('reboot', instance=instance_name,
                                                          host=instance.host)
            self.container_client.client('wait',
                        oid=data.get('operation').split('/')[3],
                        host=instance.host)
            LOG.info(_LI('Succesfully rebooted container %s'),
                     instance.uuid, instance=instance)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Failed to reboot container %(instance)s: %(reason)s'),
                    {'instance': instance.uuid, 'reason': ex}, instance=instance)

    def container_destroy(self, instance_name, host):
        LOG.debug('Container destroy')
        try:
            if not self.container_client.client('defined', instance=instance_name,
                                            host=host):
                return

            (state, data) = self.container_client.client('destroy', instance=instance_name,
                                                        host=host)
            self.container_client.client('wait',
                        oid=data.get('operation').split('/')[3],
                        host=host)
            LOG.info(_LI('Succesfully destroyed container %s'),
                     instance_name)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Failed to destroy container %(instance)s: %(reason)s'),
                    {'instance': instance_name, 'reason': ex})

    def container_pause(self, instance_name, instance):
        LOG.debug('Container pause')
        try:
            (state, data) = self.container_client.client('pause', instance=instance_name,
                                                         host=instance.host)
            timer = loopingcall.FixedIntervalLoopingCall(
                        self._wait_for_state,
                        data.get('operation').split('/')[3],
                        instance, power_state.SUSPENDED)
            timer.start(interval=CONF.lxd.retry_interval).wait()
            LOG.info(_LI('Succesfully paused container %s'),
                     instance.uuid, instance=instance)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Failed to pause container %(instance)s: %(reason)s'),
                    {'instance': instance.uuid, 'reason': ex}, instance=instance)

    def conatainer_unpause(self, instance_name, instance):
        LOG.debug('Container unpause')
        try:
            (state, data) = self.container_client.client('unpause', instance=instance_name,
                                                         host=instance.host)
            timer = loopingcall.FixedIntervalLoopingCall(
                        self._wait_for_state,
                        data.get('operation').split('/')[3],
                        instance, power_state.RUNNING)
            timer.start(interval=CONF.lxd.retry_interval).wait()
            LOG.info(_LI('Succesfully resumed container %s'),
                    instance.uuid, instance=instance)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Failed to unpause container %(instance)s: %(reason)s'),
                    {'instance': instance.uuid, 'reason': ex})

    def container_snapshot(self, container_snapshot, instance):
        try:
            (state, data) = self.container_client.client('snapshot_create',
                                                         instance=instance.uuid,
                                                         container_snapshot=container_snapshot,
                                                         host=instance.host)
            operation_id = data.get('operation').split('/')[3]
            self.container_client.client('wait', oid=operation_id,
                            host=instance.host)
            LOG.info(_LI('Succesfully snapshotted container %s'),
                 instance.uuid, instance=instance)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Failed to rename container %(instance)s: %(reason)s'),
                          {'instance': instance.uuid, 'reason': ex}, instance=instance)

    def container_copy(self, container_config, instance):
        LOG.debug('Copying container')
        try:
            (state, data) = self.container_client.client('local_copy',
                                                         container_config=container_config,
                                                         host=instance.host)
            operation_id = data.get('operation').split('/')[3]
            self.container_client.client('wait', oid=operation_id,
                            host=instance.host)
            LOG.info(_LI('Succesfully copied container %s'),
                instance.uuid, instance=instance)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Failed to rename container %(instance): %(reason)s'),
                          {'instance': instance.uuid, 'reason': ex})

    def container_move(self, old_name, container_config, instance):
        LOG.debug('Renaming container')
        try:
            (state, data) = self.container_client.client('local_move',
                                                         instance=old_name,
                                                         container_config=container_config,
                                                         host=instance.host)
            operation_id = data.get('operation').split('/')[3]
            self.container_client.client('wait', oid=operation_id,
                            host=instance.host)
            LOG.info(_LI('Succesfully renamed container %s'),
                instance.uuid, instance=instance)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Failed to rename container %(instance)s: %(reason)s'),
                          {'instance': instance.uuid, 'reason': ex}, instance=instance)

    def container_migrate(self, instance_name, instance):
        LOG.debug('Migrate contianer')
        try:
            return self.container_client.client('migrate',
                                instance=instance_name,
                                host=instance.host)
            LOG.info(_LI('Succesfully migrated container %s'),
                instance.uuid, instance=instance)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Failed to rename container %(instance): %(reason)s'),
                          {'instance': instance_name, 'reason': ex}, instance=instance)

    def container_init(self, container_config, instance, host):
        LOG.debug('Initializing container')
        try:
            (state, data) = self.container_client.client('init',
                                    container_config=container_config,
                                    host=host)
            operation_id = data.get('operation').split('/')[3]
            self.container_client.client('wait',
                    oid=operation_id,
                    host=host)
            LOG.info(_LI('Succesfully created container %s'),
                instance.uuid, instance=instance)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Failed to create container %(instance)s: %(reason)s'),
                          {'instance': instance.uuid, 'reason': ex}, instance=instance)

    def _wait_for_state(self, operation_id, instance, power_state, host=None):
        if not host:
            host = instance.host

        instance.refresh()
        (state, data) = self.container_client.client('operation_info',
                                oid=operation_id,
                                host=host)
        status_code = data['metadata']['status_code']
        if status_code in [200, 202]:
            LOG.debug('')
            instance.power_state = power_state
            instance.save()
            raise loopingcall.LoopingCallDone()

        if status_code == 400:
            LOG.debug('Initialize conainer')
            instance.power_state = power_state
            instnace.save()
            raise loopingcall.LoopingCallDone()

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
                            '%s-manifest.tar.gz' % image_meta.get('id'))

    def get_container_metadata(self, image_meta):
        return os.path.join(self.base_dir,
                            '%s-lxd.tar.xz' % image_meta.get('id'))

    def get_container_rootfsImg(self, image_meta):
        return os.path.join(self.base_dir,
                            '%s-root.tar.xz' % image_meta.get('id'))

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
