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


class ProfileMixin(object):
    """Mixin for profiles methods."""

    def profile_defined(self, instance):
        """Validate if the profile is available on the LXD
           host

           :param instance: nova instance object
        """
        LOG.debug('profile_defined called for instance',
                  instance=instance)
        try:
            client = self.get_session(instance.host)
            client.profile_defined(instance.name)
        except lxd_exceptions.APIError as ex:
            if ex.status_code == 404:
                return False
            else:
                msg = _('Failed to communicate with LXD API %(instance)s:'
                        ' %(reason)s') % {'instance': instance.name,
                                          'reason': ex}
                raise exception.NovaException(msg)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(
                    _LE('Failed to determine profile %(instance)s:'
                        ' %(reason)s'),
                    {'instance': instance.name, 'reason': ex})

    def profile_create(self, config, instance):
        """Create an LXD container profile

        :param config: profile dictionary
        :param instnace: nova instance object
        """
        LOG.debug('profile_create called for instance',
                  instance=instance)
        try:
            client = self.get_session(instance.host)
            client.profile_create(config)
        except lxd_exceptions.APIError as ex:
            msg = _('Failed to communicate with LXD API %(instance)s:'
                    ' %(reason)s') % {'instance': instance.name,
                                      'reason': ex}
            raise exception.NovaException(msg)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(
                    _LE('Failed to create profile %(instance)s: %(reason)s'),
                    {'instance': instance.name, 'reason': ex})

    def profile_update(self, config, instance):
        """Update an LXD container profile

          :param config: LXD profile dictironary
          :param instance: nova instance object
        """
        LOG.debug('profile_udpate called for instance', instance=instance)
        try:
            client = self.get_session(instance.host)
            client.profile_update(instance.name, config)
        except lxd_exceptions.APIError as ex:
            msg = _('Failed to communicate with LXD API %(instance)s:'
                    ' %(reason)s') % {'instance': instance.name,
                                      'reason': ex}
            raise exception.NovaException(msg)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(
                    _LE('Failed to update profile %(instance)s: '
                        '%(reason)s'),
                    {'instance': instance.name, 'reason': ex})

    def profile_delete(self, instance):
        """Delete a LXD container profile.

           :param instance: nova instance object
        """
        LOG.debug('profile_delete called for instance', instance=instance)
        try:
            client = self.get_session(instance.host)
            client.profile_delete(instance.name)
        except lxd_exceptions.APIError as ex:
            msg = _('Failed to communicate with LXD API %(instance)s:'
                    ' %(reason)s') % {'instance': instance.name,
                                      'reason': ex}
            raise exception.NovaException(msg)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(
                    _LE('Failed to delete profile %(instance)s: %(reason)s'),
                    {'instance': instance.name, 'reason': ex})
