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

from oslo_config import cfg
from oslo_log import log as logging
from oslo_service import loopingcall
from oslo_utils import excutils

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
        instance.refresh()
        (state, data) = self.container_client.client('start', instance=instance_name,
                                                     host=instance.host)

        def _wait_for_start(id, instance):
            instance.refresh()
            (state, data) = self.container_client.client('operation_info',
                                                         oid=id,
                                                         host=instance.host)
            status_code = data['metadata']['status_code']
            if status_code in [100, 101, 200]:
                instance.vm_sate = vm_states.ACTIVE
                instance.save()
                raise loopingcall.LoopingCallDone()
            elif status_code in [101, 106]:
                instance.power_state = power_state.NOSTATE
                instance.vm_state = vm_states.BUILDING
                instance.save()
            elif status_code in [104, 108]:
                instance.power_state = power_state.CRASHED
                instance.vm_state = vm_states.ERROR
                instance.save()
                raise loopingcall.LoopingCallDone()
            elif status_code in [400, 401]:
                instance.power_state = power_state.CRASHED
                instance.vm_state = vm_states.ERROR
                instance.save()
                raise loopingcall.LoopingCallDone()

        operation_id = data.get('operation').split('/')[3]
        timer = loopingcall.FixedIntervalLoopingCall(_wait_for_start,
                                                     operation_id,
                                                     instance)

        try:
            timer.start(interval=CONF.lxd.retry_interval).wait()
            LOG.info(_LI('Succesfully launched container %s'),
                     instance.uuid, instance=instance)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE("Error deploying instance %(instance)s"),
                          {'instance': instance.uuid})

    def container_stop(self, instance_name, instance):
        instance.refresh()
        (state, data) = self.container_client.client('stop', instance=instance_name,
                                                     host=instance.host)

        def _wait_for_stop(id, instance):
            instance.refresh()
            (state, data) = self.container_client.client('operation_info',
                                                         oid=id,
                                                         host=instance.host)
            status_code = data['metadata']['status_code']
            if status_code in [100, 102, 200]:
                instance.power_state = power_state.SHUTDOWN
                instance.task_state = None
                instance.save()
                raise loopingcall.LoopingCallDone()
            elif status_code == 107:
                instance.power_state = power_state.NOSTATE
                instance.vm_state = vm_states.ACTIVE
                instance.task_state = task_states.POWERING_OFF
                instance.save()
                raise loopingcall.LoopingCallDone()
            elif status_code in [400, 401]:
                instance.power_state = power_state.CRASHED
                instance.vm_state = vm_states.ERROR
                instance.save()
                raise loopingcall.LoopingCallDone()

        operation_id = data.get('operation').split('/')[3]
        timer = loopingcall.FixedIntervalLoopingCall(_wait_for_stop,
                                                     operation_id, instance)

        try:
            timer.start(interval=CONF.lxd.retry_interval).wait()
            LOG.info(_LI('Succesfully stopped container %s'),
                     instance.uuid, instance=instance)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE("Error deploying instance %(instance)s"),
                          {'instance': instance.uuid})

    def container_reboot(self, instance_name,  instance):
        instance.refresh()
        (state, data) = self.container_client.client('reboot', instance=instance_name,
                                                     host=instance.host)

        def _wait_for_reboot(oid, instance):
            instance.refresh()
            (state, data) = self.container_client.client('operation_info',
                                                         oid=id,
                                                         host=instance.host)
            status_code = data['metadata']['status_code']
            if status_code in [100, 101, 103, 200]:
                instance.power_state = power_state.RUNNING
                instance.vm_sate = vm_states.ACTIVE
                instance.save()
                raise loopingcall.LoopingCallDone()
            elif status_code in [108, 400, 401]:
                instance.power_state = power_state.CRASHED
                instance.vm_state = vm_states.ERROR
                instance.save()
                raise loopingcall.LoopingCallDone()

        operation_id = data.get('operation').split('/')[3]
        timer = loopingcall.FixedIntervalLoopingCall(_wait_for_reboot,
                                                     operation_id, instance)

        try:
            timer.start(interval=CONF.lxd.retry_interval).wait()
            LOG.info(_LI('Succesfully rebooted container %s'),
                     instance.uuid, instance=instance)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE("Error deploying instance %(instance)s"),
                          {'instance': instance.uuid})

    def container_destroy(self, instance_name, instance):
        if not self.container_client.client('defined', instance=instance_name,
                                            host=instance.host):
            return

        def _wait_for_destroy(oid, instance):
            (state, data) = self.container_client.client('operation_info',
                                                         oid=oid, host=instance.host)

            status_code = data['metadata']['status_code']
            if status_code in [100, 200]:
                LOG.debug('Sucessfully deleted')
                raise loopingcall.LoopingCallDone()
            if status_code in [400, 401]:
                LOG.debug('Failed to delete')
                raise loopingcall.LoopingCallDone()
            else:
                LOG.debug('Waiting for delete')

        (state, data) = self.container_client.client('destroy', instance=instance.uuid,
                                                     host=instance.host)
        operation_id = data.get('operation').split('/')[3]
        timer = loopingcall.FixedIntervalLoopingCall(_wait_for_destroy,
                                                     operation_id, instance)

        try:
            timer.start(interval=CONF.lxd.retry_interval).wait()
            LOG.info(_LI('Succesfully destroyed container %s'),
                     instance.uuid, instance=instance)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE("Error deploying instance %(instance)s"),
                          {'instance': instance.uuid})

    def container_pause(self, instance_name, instance):
        instance.refresh()
        (state, data) = self.container_client.client('pause', instance=instance_name,
                                                     host=instance.host)

        def _wait_for_pause(id, instance):
            instance.refresh()
            (state, data) = self.container_client.client('operation_info',
                                                         oid=id,
                                                         host=instance.host)
            status_code = data['metadata']['status_code']
            if status_code in [100, 200, 110]:
                instance.power_state = power_state.PAUSED
                instance.task_state = task_states.SCHEDULING
                instance.save()
                raise loopingcall.LoopingCallDone()
            elif status_code == 109:
                instance.power_stae = power_state.NOSTATE
                instance.task_state = task_states.PAUSING
                instance.save()
            elif status_code in [400, 401]:
                instance.power_stae = power_state.CRASHED
                instance.state()
            else:
                instance.power_stae = power_state.NOSTATE
                instance.task_sate = task_states.SCHEDULING
                instance.state()

        operation_id = data.get('operation').split('/')[3]
        timer = loopingcall.FixedIntervalLoopingCall(_wait_for_pause,
                                                     operation_id, instance)
        try:
            timer.start(interval=CONF.lxd.retry_interval).wait()
            LOG.info(_LI('Succesfully paused container %s'),
                     instance.uuid, instance=instance)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE("Error deploying instance %(instance)s"),
                          {'instance': instance.uuid})

    def conatainer_unpause(self, instance_name, instance):
        (state, data) = self.container_client.client('unpause', instance=instance_name,
                                                     host=instance.host)

        def _wait_for_unpause(id, instance):
            instance.refresh()
            (state, data) = self.container_client.client('operation_info',
                                                         oid=id,
                                                         host=instance.host)
            status_code = data['metadata']['status_code']
            if status_code in [100, 110, 200]:
                instance.power_state = power_state.RUNNING
                instance.vm_state = vm_states.ACTIVE
                instance.save()
                raise loopingcall.LoopingCallDone()
            if status_code == 109:
                instance.task_state = task_states.RESTORING
                instance.save()
            elif status_code in [400, 401]:
                instance.power_stae = power_state.CRASHED
                instance.state()
            else:
                instance.power_stae = power_state.NOSTATE
                instance.task_sate = task_states.SCHEDULING
                instance.state()

        operation_id = data.get('operation').split('/')[3]
        timer = loopingcall.FixedIntervalLoopingCall(_wait_for_unpause,
                                                     operation_id, instance)

        try:
            timer.start(interval=CONF.lxd.retry_interval).wait()
            LOG.info(_LI('Succesfully unpaused container %s'),
                     instance.uuid, instance=instance)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE("Error deploying instance %(instance)s"),
                          {'instance': instance.uuid})

    def container_snapshot(self, container_snapshot, instance):
        (state, data) = self.container_client.client('snapshot_create',
                                                     instance=instance.uuid,
                                                     container_snapshot=container_snapshot,
                                                     host=instance.host)

        def _wait_for_snapshot(oid, instance):
            (state, data) = self.container_client.client('operation_info',
                                                         oid=oid,
                                                         host=instance.host)
            status_code = data['metadata']['status_code']
            if status_code in [200, 100]:
                LOG.debug('Created snaspshot')
                raise loopingcall.LoopingCallDone()
            elif status_code in [400, 401]:
                LOG.debug('Failed to create snapshot')
                raise loopingcall.LoopingCallDone()
            else:
                LOG.debug('Creating snapshot')

        operation_id = data.get('operation').split('/')[3]
        timer = loopingcall.FixedIntervalLoopingCall(_wait_for_snapshot,
                                                     operation_id, instance)

        try:
            timer.start(interval=CONF.lxd.retry_interval).wait()
            LOG.info(_LI('Succesfully unpaused container %s'),
                     instance.uuid, instance=instance)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE("Error deploying instance %(instance)s"),
                          {'instance': instance.uuid})


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
