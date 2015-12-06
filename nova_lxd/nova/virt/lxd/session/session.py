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

from oslo_config import cfg
from oslo_log import log as logging

from nova_lxd.nova.virt.lxd.session import container
from nova_lxd.nova.virt.lxd.session import event
from nova_lxd.nova.virt.lxd.session import image
from nova_lxd.nova.virt.lxd.session import migrate
from nova_lxd.nova.virt.lxd.session import snapshot

_ = i18n._
_LE = i18n._LE

CONF = cfg.CONF
CONF.import_opt('host', 'nova.netconf')
LOG = logging.getLogger(__name__)


class LXDAPISession(container.ContainerMixin,
                    event.EventMixin,
                    image.ImageMixin,
                    migrate.MigrateMixin,
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
