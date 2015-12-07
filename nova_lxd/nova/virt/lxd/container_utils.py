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
from nova import utils

from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils
import six

from nova_lxd.nova.virt.lxd import container_client
from nova_lxd.nova.virt.lxd.session import session


_ = i18n._
_LE = i18n._LE
_LW = i18n._LW
_LI = i18n._LI

CONF = cfg.CONF
LOG = logging.getLogger(__name__)


class LXDContainerUtils(object):

    def __init__(self):
        self.session = session.LXDAPISession()
        self.client = container_client.LXDContainerClient()

    def container_start(self, instance_name, instance):
        LOG.debug('Container start')
        try:
            (state, data) = self.client.client('start', instance=instance_name,
                                               host=instance.host)
            self.session.operation_wait(data.get('operation'), instance)
            LOG.info(_LI('Successfully started instance %s'),
                     instance_name, instance=instance)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(
                    _LE('Failed to start container %(instance)s: %(reason)s'),
                    {'instance': instance_name, 'reason': ex},
                    instance=instance)

    def container_stop(self, instance_name, host, instance):
        LOG.debug('Container stop')
        try:
            (state, data) = (self.client.client('stop',
                                                instance=instance_name,
                                                host=host))
            self.session.operation_wait(data.get('operation'), instance)
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
                                               instance=instance.name,
                                               host=instance.host)
            self.session.operation_wait(data.get('operation'), instance)
            LOG.info(_LI('Successfully rebooted container %s'),
                     instance.name, instance=instance)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(
                    _LE('Failed to reboot container %(instance)s: '
                        '%(reason)s'), {'instance': instance.name,
                                        'reason': ex}, instance=instance)

    def container_destroy(self, instance_name, host, instance):
        LOG.debug('Container destroy')
        try:
            if not self.client.client(
                    'defined', instance=instance_name,
                    host=host):
                return

            self.container_stop(instance_name, host, instance)

            (state, data) = self.client.client('destroy',
                                               instance=instance_name,
                                               host=host)
            self.session.operation_wait(data.get('operation'), instance)
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
            self.session.operation_wait(data.get('operation'), instance)
            LOG.info(_LI('Successfully paused container %s'),
                     instance.name, instance=instance)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(
                    _LE('Failed to pause container %(instance)s: '
                        '%(reason)s'),
                    {'instance': instance.name,
                     'reason': ex}, instance=instance)

    def container_unpause(self, instance_name, instance):
        LOG.debug('Container unpause')
        try:
            (state, data) = self.client.client('unpause',
                                               instance=instance_name,
                                               host=instance.host)
            self.session.operation_wait(data.get('operation'), instance)
            LOG.info(_LI('Successfully resumed container %s'),
                     instance_name, instance=instance)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(
                    _LE('Failed to unpause container %(instance)s: '
                        '%(reason)s'), {'instance': instance_name,
                                        'reason': ex})

    def container_snapshot(self, snapshot, instance):
        try:
            (state, data) = self.client.client('snapshot_create',
                                               instance=instance.name,
                                               container_snapshot=snapshot,
                                               host=instance.host)
            self.session.operation_wait(data.get('operation'), instance)
            LOG.info(_LI('Successfully snapshotted container %s'),
                     instance.name, instance=instance)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(
                    _LE('Failed to rename container %(instance)s: %(reason)s'),
                    {'instance': instance.name,
                     'reason': ex}, instance=instance)

    def container_copy(self, config, instance):
        LOG.debug('Copying container')
        try:
            (state, data) = self.client.client('local_copy',
                                               container_config=config,
                                               host=instance.host)
            self.session.operation_wait(data.get('operation'), instance)
            LOG.info(_LI('Successfully copied container %s'),
                     instance.name, instance=instance)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(
                    _LE('Failed to rename container %(instance): %(reason)s'),
                    {'instance': instance.name,
                     'reason': ex})

    def container_move(self, old_name, config, instance):
        LOG.debug('Renaming container')
        try:
            (state, data) = (self.client.client('local_move',
                                                instance=old_name,
                                                container_config=config,
                                                host=instance.host))
            self.session.operation_wait(data.get('operation'), instance)
            LOG.info(_LI('Successfully renamed container %s'),
                     instance.name, instance=instance)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(
                    _LE('Failed to rename container %(instance)s: %(reason)s'),
                    {'instance': instance.name,
                     'reason': ex}, instance=instance)

    def container_migrate(self, instance_name, host):
        LOG.debug('Migrate contianer')
        try:
            return self.client.client('migrate',
                                      instance=instance_name,
                                      host=host)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(
                    _LE('Failed to rename container %(instance): %(reason)s'),
                    {'instance': instance_name,
                     'reason': ex})

    def container_init(self, config, instance, host):
        LOG.debug('Initializing container')
        try:
            (state, data) = self.client.client('init',
                                               container_config=config,
                                               host=host)

            operation = data.get('operation')
            self.session.operation_wait(operation, instance)
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
                    {'instance': instance.name,
                     'reason': ex}, instance=instance)

    def mount_filesystem(self, dev_path, dir_path):
        try:
            _out, err = utils.execute('mount',
                                      '-t', 'ext4',
                                      dev_path, dir_path, run_as_root=True)
        except processutils.ProcessExecutionError as e:
            err = six.text_type(e)
        return err

    def umount_filesystem(self, dir_path):
        try:
            _out, err = utils.execute('umount',
                                      dir_path, run_as_root=True)
        except processutils.ProcessExecutionError as e:
            err = six.text_type(e)
        return err
