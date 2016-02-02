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

from nova import context as nova_context
from nova import exception
from nova import i18n
from nova import rpc
from pylxd import api
from pylxd import exceptions as lxd_exceptions

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils

from nova_lxd.nova.virt.lxd.session import container
from nova_lxd.nova.virt.lxd.session import event
from nova_lxd.nova.virt.lxd.session import migrate
from nova_lxd.nova.virt.lxd.session import profile
from nova_lxd.nova.virt.lxd.session import snapshot

_ = i18n._
_LE = i18n._LE

CONF = cfg.CONF
CONF.import_opt('host', 'nova.netconf')
LOG = logging.getLogger(__name__)


class LXDAPISession(container.ContainerMixin,
                    event.EventMixin,
                    migrate.MigrateMixin,
                    profile.ProfileMixin,
                    snapshot.SnapshotMixin):
    """The session to invoke the LXD API session."""

    def __init__(self):
        super(LXDAPISession, self).__init__()

    def get_session(self, host=None):
        """Returns a connection to the LXD hypervisor

        This method should be used to create a connection
        to the LXD hypervisor via the pylxd API call.

        :param host: host is the LXD daemon to connect to
        :return: pylxd object
        """
        try:
            if host is None:
                conn = api.API()
            elif host == CONF.host:
                conn = api.API()
            else:
                conn = api.API(host=host)
        except Exception as ex:
            # notify the compute host that the connection failed
            # via an rpc call
            LOG.exception(_LE('Connection to LXD failed'))
            payload = dict(ip=CONF.host,
                           method='_connect',
                           reason=ex)
            rpc.get_notifier('compute').error(nova_context.get_admin_context,
                                              'compute.nova_lxd.error',
                                              payload)
            raise exception.HypervisorUnavailable(host=CONF.host)

        return conn

    #
    # Image related API methods.
    #

    def image_defined(self, instance):
        """Checks existence of an image on the local LXD image store

        :param instance: The nova instance

        Returns True if supplied image exists on the host, False otherwise
        """
        LOG.debug('image_defined called for instance', instance=instance)
        try:
            client = self.get_session(instance.host)
            return client.alias_defined(instance.image_ref)
        except lxd_exceptions.APIError as ex:
            if ex.status_code == 404:
                return False
            else:
                msg = _('Failed to communicate with LXD API %(instance)s:'
                        ' %(reason)s') % {'instance': instance.image_ref,
                                          'reason': ex}
                LOG.error(msg)
                raise exception.NovaException(msg)
        except Exception as e:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Error from LXD during image_defined '
                              '%(instance)s: %(reason)s'),
                          {'instance': instance.image_ref, 'reason': e},
                          instance=instance)

    def create_alias(self, alias, instance):
        """Creates an alias for a given image

        :param alias: The alias to be crerated
        :param instance: The nove instnace
        :return: true if alias is created, false otherwise

        """
        LOG.debug('create_alias called for instance', instance=instance)
        try:
            client = self.get_session(instance.host)
            return client.alias_create(alias)
        except lxd_exceptions.APIError as ex:
            msg = _('Failed to communicate with LXD API %(instance)s:'
                    ' %(reason)s') % {'instance': instance.image_ref,
                                      'reason': ex}
            LOG.error(msg)
            raise exception.NovaException(msg)
        except Exception as e:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Error from LXD during create alias'
                              '%(instance)s: %(reason)s'),
                          {'instance': instance.image_ref, 'reason': e},
                          instance=instance)

    def image_upload(self, data, headers, instance):
        """Upload an image to the local LXD image store

        :param data: image data
        :param headers: image headers
        :param intance: The nova instance

        """
        LOG.debug('upload_image called for instnace', instance=instance)
        try:
            client = self.get_session(instance.host)
            (state, data) = client.image_upload(data=data,
                                                headers=headers)
            # XXX - zulcss (Dec 8, 2015) - Work around for older
            # versions of LXD.
            if 'operation' in data:
                self.operation_wait(data.get('operation'), instance)
        except lxd_exceptions.APIError as ex:
            msg = _('Failed to communicate with LXD API %(instance)s:'
                    '%(reason)s') % {'instance': instance.image_ref,
                                     'reason': ex}
            LOG.error(msg)
            raise exception.NovaException(msg)
        except Exception as e:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Error from LXD during image upload'
                              '%(instance)s: %(reason)s'),
                          {'instance': instance.image_ref, 'reason': e},
                          instance=instance)
