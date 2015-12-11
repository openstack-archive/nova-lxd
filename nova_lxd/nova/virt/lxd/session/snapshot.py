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
from oslo_utils import excutils

_ = i18n._
_LE = i18n._LE
_LI = i18n._LI

CONF = cfg.CONF
LOG = logging.getLogger(__name__)


class SnapshotMixin(object):

    def container_copy(self, config, instance):
        """Copy a LXD container

        :param config: LXD container configuration
        :param instance: nova instance object

        """
        LOG.debug('container_copy called for instance', instance=instance)
        try:
            LOG.info(_LI('Copying container %(instance)s with'
                         '%(image)s'), {'instance': instance.name,
                                        'image': instance.image_ref})

            client = self.get_session(instance.host)
            (state, data) = client.contianer_local_copy(config)
            self.operation_wait(data.get('operation'), instance)
            LOG.info(_LI('Successfully copied container %(instance)s with'
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
                    _LE('Failed to copy container %(instance)s: %(reason)s'),
                    {'instance': instance.name,
                     'reason': ex})

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
            LOG.info(_LI('Snapshotting container %(instance)s with'
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
            return client.image_export(image)
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
        try:
            client = self.get_session(instance.host)
            return client.image_export(image)
        except lxd_exceptions.APIError as ex:
            msg = _('Failed to export image: %s') % ex
            raise exception.NovaException(msg)
