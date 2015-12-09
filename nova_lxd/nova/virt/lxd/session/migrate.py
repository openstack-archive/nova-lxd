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


class MigrateMixin(object):
    """Migrate LXD oerations."""

    def container_migrate(self, instance_name, host, instance):
        """Initialize a container migration for LXD

        :param instance_name: container name
        :param host: host to move container from
        :param instance: nova instance object
        :return: dictionary of the container keys

        """
        LOG.debug('container_migrate called for instance', isntance=instance)
        try:
            LOG.info(_LI('Migrating instance %(instance)s with'
                         '%(image)s'), {'instance': instance_name,
                                        'image': instance.image_ref})

            client = self.get_session(host)
            (state, data) = client.container_migrate(instance_name)

            LOG.info(_LI('Successfully initialized migration for instance '
                         '%(instance)s with %(image)s'),
                     {'instance': instance.name,
                      'image': instance.image_ref})
            return (state, data)
        except lxd_exceptions.APIError as ex:
            msg = _('Failed to communicate with LXD API %(instance)s:'
                    ' %(reason)s') % {'instance': instance.name,
                                      'reason': ex}
            raise exception.NovaException(msg)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(
                    _LE('Failed to migrate container %(instance)s: %('
                        'reason)s'), {'instance': instance.name,
                                      'reason': ex}, instance=instance)
