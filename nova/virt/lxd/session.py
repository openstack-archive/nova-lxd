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

import nova.conf
from nova import context as nova_context
from nova import exception
from nova import i18n
from nova import rpc

from oslo_log import log as logging
from oslo_utils import excutils

from pylxd.deprecated import api
from pylxd.deprecated import exceptions as lxd_exceptions

_ = i18n._

CONF = nova.conf.CONF
LOG = logging.getLogger(__name__)


class LXDAPISession(object):
    """The session to invoke the LXD API session."""

    def get_session(self, host=None):
        """Returns a connection to the LXD hypervisor

        This method should be used to create a connection
        to the LXD hypervisor via the pylxd API call.

        :param host: host is the LXD daemon to connect to
        :return: pylxd object
        """
        try:
            if host:
                return api.API(host=host)
            else:
                return api.API()
        except Exception as ex:
            # notify the compute host that the connection failed
            # via an rpc call
            LOG.exception("Connection to LXD failed")
            payload = dict(ip=CONF.host,
                           method='_connect',
                           reason=ex)
            rpc.get_notifier('compute').error(nova_context.get_admin_context,
                                              'compute.nova_lxd.error',
                                              payload)
            raise exception.HypervisorUnavailable(host=CONF.host)

    #
    # Container related API methods
    #
    def container_init(self, config, instance, host=None):
        """Create a LXD container

        :param config: LXD container config as a dict
        :param instance: nova instance object
        :param host: perform initialization on perfered host
        """
        try:
            LOG.info("Creating container {instance} with {image}"
                     .format(instance=instance.name,
                             image=instance.image_ref),
                     instance=instance)

            client = self.get_session(host=host)
            (state, data) = client.container_init(config)
            operation = data.get('operation')
            self.operation_wait(operation, instance, host=host)
            status, data = self.operation_info(operation, instance, host=host)
            data = data.get('metadata')
            if not data['status_code'] == 200:
                msg = data.get('err') or data['metadata']
                raise exception.NovaException(msg)

            LOG.info("Successfully created container {instance} with {image}"
                     .format(instance=instance.name,
                             image=instance.image_ref),
                     instance=instance)
        except lxd_exceptions.APIError as ex:
            msg = (_("Failed to communicate with LXD API {instance}: {reason}")
                   .format(instance=instance.name, reason=ex))
            raise exception.NovaException(msg)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error("Failed to create container {instance}: {reason}"
                          .format(instance=instance.name, reason=ex),
                          instance=instance)

    #
    # Operation methods
    #

    def operation_wait(self, operation_id, instance, host=None):
        """Waits for an operation to return 200 (Success)

        :param operation_id: The operation to wait for.
        :param instance: nova instace object
        """
        LOG.debug("wait_for_container for instance", instance=instance)
        try:
            client = self.get_session(host=host)
            if not client.wait_container_operation(operation_id, 200, -1):
                msg = _("Container creation timed out")
                raise exception.NovaException(msg)
        except lxd_exceptions.APIError as ex:
            msg = _("Failed to communicate with LXD API {instance}: "
                    "{reason}").format(instance=instance.image_ref,
                                       reason=ex)
            LOG.error(msg, instance=instance)
            raise exception.NovaException(msg)
        except Exception as e:
            with excutils.save_and_reraise_exception():
                LOG.error("Error from LXD during operation wait "
                          "{instance}: {reason}"
                          .format(instance=instance.image_ref, reason=e))

    def operation_info(self, operation_id, instance, host=None):
        LOG.debug("operation_info called for instance", instance=instance)
        try:
            client = self.get_session(host=host)
            return client.operation_info(operation_id)
        except lxd_exceptions.APIError as ex:
            msg = _("Failed to communicate with LXD API {instance}:"
                    " {reason}").format(instance=instance.image_ref,
                                        reason=ex)
            LOG.error(msg, instance=instance)
            raise exception.NovaException(msg)
        except Exception as e:
            with excutils.save_and_reraise_exception():
                LOG.error("Error from LXD during operation_info "
                          "{instance}: {reason}"
                          .format(instance=instance.image_ref, reason=e))

    #
    # Migrate methods
    #
    def container_migrate(self, instance_name, host, instance):
        """Initialize a container migration for LXD

        :param instance_name: container name
        :param host: host to move container from
        :param instance: nova instance object
        :return: dictionary of the container keys

        """
        LOG.debug("container_migrate called for instance", instance=instance)
        try:
            LOG.info("Migrating instance {instance} with {image}"
                     .format(instance=instance_name,
                             image=instance.image_ref))

            client = self.get_session()
            (state, data) = client.container_migrate(instance_name)

            LOG.info("Successfully initialized migration for instance "
                     "{instance} with {image}"
                     .format(instance=instance.name,
                             image=instance.image_ref))
            return (state, data)
        except lxd_exceptions.APIError as ex:
            msg = _("Failed to communicate with LXD API {instance}:"
                    " {reason}").format(instance=instance.name,
                                        reason=ex)
            raise exception.NovaException(msg)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error("Failed to migrate container {instance}: {reason}"
                          .format(instance=instance.name, reason=ex))
