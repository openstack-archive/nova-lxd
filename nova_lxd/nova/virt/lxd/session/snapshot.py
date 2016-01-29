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
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See
#    the License for the specific language governing permissions and
#    limitations under the License.

from nova import exception
from nova import i18n
from pylxd import exceptions as lxd_exceptions

from oslo_config import cfg
from oslo_log import log as logging
from oslo_service import loopingcall
from oslo_utils import excutils

_ = i18n._
_LE = i18n._LE
_LI = i18n._LI

CONF = cfg.CONF
LOG = logging.getLogger(__name__)


class SnapshotMixin(object):

    def container_move(self, old_name, config, instance):
        """Move a container from one host to another

        :param old_name: Old container name
        :param config:  Old container config
        :param instance: nova instance object
        :return:

        """
        LOG.debug('container_move called for instance', instnace=instance)
        try:
            LOG.info(_LI('Moving container %(instance)s with'
                         '%(image)s'), {'instance': instance.name,
                                        'image': instance.image_ref})

            # Container move
            client = self.get_session(instance.host)
            (state, data) = client.container_local_move(old_name, config)
            self.operation_wait(data.get('operation'), instance)

            LOG.info(_LI('Successfully moved container %(instance)s with'
                         '%(image)s'), {'instance': instance.name,
                                        'image': instance.image_ref})
        except lxd_exceptions.APIError as ex:
            msg = _('Failed to communicate with LXD API %(instance)s:'
                    ' %(reason)s') % {'instance': instance.name,
                                      'reason': ex}
            raise exception.NovaException(msg)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(
                    _LE('Failed to move container %(instance)s: %('
                        'reason)s'),
                    {'instance': instance.name,
                     'reason': ex}, instance=instance)

    def container_snapshot(self, snapshot, instance):
        """Snapshot a LXD container

        :param snapshot: snapshot config dictionary
        :param instance: nova instance object

        """
        LOG.debug('container_snapshot called for instance', instance=instance)
        try:
            LOG.info(_LI('Snapshotting container %(instance)s with '
                         '%(image)s'), {'instance': instance.name,
                                        'image': instance.image_ref})

            # Container snapshot
            client = self.get_session(instance.host)
            (state, data) = client.container_snapshot_create(
                instance.name, snapshot)
            self.operation_wait(data.get('operation'), instance)

            LOG.info(_LI('Successfully snapshotted container %(instance)s with'
                         '%(image)s'), {'instance': instance.name,
                                        'image': instance.image_ref})
        except lxd_exceptions.APIError as ex:
            msg = _('Failed to communicate with LXD API %(instance)s:'
                    ' %(reason)s') % {'instance': instance.name,
                                      'reason': ex}
            raise exception.NovaException(msg)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(
                    _LE('Failed to snapshot container %(instance)s: '
                        '%(reason)s'),
                    {'instance': instance.name,
                     'reason': ex}, instance=instance)

    def container_publish(self, image, instance):
        """Publish a container to the local LXD image store

        :param image: LXD fingerprint
        :param instance: nova instance object
        :return: True if published, False otherwise

        """
        LOG.debug('container_publish called for instance', instance=instance)
        try:
            client = self.get_session(instance.host)
            return client.container_publish(image)
        except lxd_exceptions.APIError as ex:
            msg = _('Failed to communicate with LXD API %(instance)s:'
                    ' %(reason)s') % {'instance': instance.name,
                                      'reason': ex}
            raise exception.NovaException(msg)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(
                    _LE('Failed to publish container %(instance)s: '
                        '%(reason)s'),
                    {'instance': instance.name,
                     'reason': ex}, instance=instance)

    def container_export(self, image, instance):
        """
        Export an image from the local LXD image store into
        an file.

        :param image: image dictionary
        :param instance: nova instance object
        """
        LOG.debug('container_export called for instance', instance=instance)
        try:
            client = self.get_session(instance.host)
            return client.image_export(image)
        except lxd_exceptions.APIError as ex:
            msg = _('Failed to export image: %s') % ex
            raise exception.NovaException(msg)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(
                    _LE('Failed to export container %(instance)s: '
                        '%(reason)s'),
                    {'instance': instance.name,
                     'reason': ex}, instance=instance)

    def wait_for_snapshot(self, event_id, instance):
        """Poll snapshot operation for the snapshot to be ready.

        :param event_id: operation id
        :param instnace: nova instance object
        """
        LOG.debug('wait_for_snapshot called for instance', instance=instance)

        timer = loopingcall.FixedIntervalLoopingCall(self._wait_for_snapshot,
                                                     event_id, instance)
        try:
            timer.start(interval=2).wait()
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Failed to create snapshot for %(instance)s: '
                              '%(ex)s'), {'instance': instance.name, 'ex': ex},
                          instance=instance)

    def _wait_for_snapshot(self, event_id, instance):
        """Check the status code of the opeation id.

        :param event_id: operation id
        :param instance: nova instance object
        """
        client = self.get_session(instance.host)
        (state, data) = client.operation_info(event_id)
        status_code = data['metadata']['status_code']

        if status_code == 200:
            raise loopingcall.LoopingCallDone()
        elif status_code == 400:
            msg = _('Snapshot failed')
            raise exception.NovaException(msg)
