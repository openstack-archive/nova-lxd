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

CONF = cfg.CONF
LOG = logging.getLogger(__name__)


class EventMixin(object):
    """Operation functions for LXD."""

    def operation_wait(self, operation_id, instance):
        """Waits for an operation to return 200 (Success)

        :param operation_id: The operation to wait for.
        """
        LOG.debug('wait_for_contianer for instance', isntance=instance)
        try:
            client = self.get_session(instance.host)
            if not client.wait_container_operation(operation_id, 200, -1):
                msg = _('Container creation timed out')
                raise exception.NovaException(msg)
        except lxd_exceptions.APIError as ex:
            msg = _('Failed to communicate with LXD API %(isntance)s:'
                    '%(reason)s') % {'instance': instance.image_ref,
                                     'reason': ex}
            LOG.error(msg)
            raise exception.NovaException(msg)
        except Exception as e:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Error from LXD during image_defined '
                              '%(instance)s: %(reason)s'),
                          {'instance': instance.image_ref, 'reason': e},
                          instance=instance)
