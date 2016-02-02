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
from nova.compute import power_state
from pylxd import api
from pylxd import exceptions as lxd_exceptions

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils

from nova_lxd.nova.virt.lxd import constants
from nova_lxd.nova.virt.lxd.session import migrate
from nova_lxd.nova.virt.lxd.session import profile
from nova_lxd.nova.virt.lxd.session import snapshot

_ = i18n._
_LE = i18n._LE
_LI = i18n._LI

CONF = cfg.CONF
CONF.import_opt('host', 'nova.netconf')
LOG = logging.getLogger(__name__)


class LXDAPISession(migrate.MigrateMixin,
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
    # Container related API methods
    #

    def container_list(self):
        """List of containers running on a given host

        Returns a list of running containers

        """
        LOG.debug('container_list called')
        try:
            client = self.get_session()
            return client.container_list()
        except lxd_exceptions.APIError as ex:
            msg = _('Failed to communicate with LXD API: %(reason)s') \
                % {'reason': ex}
            LOG.error(msg)
            raise exception.NovaException(msg)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Error from LXD during container_list: '
                              '%(reason)s') % {'reason': ex})

    def container_update(self, config, instance):
        """Update the LXD configuration of a given container

        :param config: LXD configuration dictionary
        :param instance: nova instance object
        :return: an update LXD configuration dictionary

        """
        LOG.debug('container_update called fo instance', instance=instance)
        try:
            client = self.get_session(instance.host)
            if not self.container_defined(instance.name, instance):
                msg = _('Instance is not found..: %s') % instance.name
                raise exception.InstanceNotFound(msg)

            return client.container_update(instance.name,
                                           config)
        except lxd_exceptions.APIError as ex:
            msg = _('Failed to communicate with LXD API %(instance)s:'
                    ' %(reason)s') % {'instance': instance.name,
                                      'reason': ex}
            raise exception.NovaException(msg)
        except Exception as e:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Error from LXD during container_update'
                              '%(instance)s: %(reason)s'),
                          {'instance': instance.name, 'reason': e},
                          instance=instance)

    def container_running(self, instance):
        """Determine if the container is running

        :param instance: nova instance object
        :return: True if container is running otherwise false

        """
        LOG.debug('container_running for instance', instance=instance)
        try:
            client = self.get_session(instance.host)
            return client.container_running(instance.name)
        except lxd_exceptions.APIError as ex:
            msg = _('Failed to communicate with LXD API %(instance)s:'
                    ' %(reason)s') % {'instance': instance.name,
                                      'reason': ex}
            raise exception.NovaException(msg)
        except Exception as e:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Error from LXD during container_running'
                              '%(instance)s: %(reason)s'),
                          {'instance': instance.name, 'reason': e},
                          instance=instance)

    def container_state(self, instance):
        """Determine container_state and translate state

        :param instance: nova instance object
        :return: nova power_state

        """
        LOG.debug('container_state called for instance', instance=instance)
        try:
            client = self.get_session(instance.host)
            if not self.container_defined(instance.name, instance):
                return power_state.NOSTATE

            (state, data) = client.container_state(instance.name)
            state = constants.LXD_POWER_STATES[data['metadata']['status_code']]
        except lxd_exceptions.APIError as ex:
            msg = _('Failed to communicate with LXD API %(instance)s:'
                    ' %(reason)s') % {'instance': instance.name,
                                      'reason': ex}
            LOG.error(msg)
            state = power_state.NOSTATE
        except Exception as e:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Error from LXD during container_state'
                              '%(instance)s: %(reason)s'),
                          {'instance': instance.name, 'reason': e},
                          instance=instance)
                state = power_state.NOSTATE
        return state

    def container_config(self, instance):
        """Fetches the configuration of a given LXD container

        :param instance: nova instance object
        :return: dictionary represenation of a LXD container

        """
        LOG.debug('container_config called for instance', instance=instance)
        try:
            if not self.container_defined(instance.name, instance):
                msg = _('Instance is not found.. %s') % instance.name
                raise exception.InstanceNotFound(msg)

            client = self.get_session(instance.host)
            return client.get_container_config(instance.name)
        except lxd_exceptions.APIError as ex:
            msg = _('Failed to communicate with LXD API %(instance)s:'
                    ' %(reason)s') % {'instance': instance.name,
                                      'reason': ex}
            raise exception.NovaException(msg)
        except Exception as e:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Error from LXD during container_config'
                              '%(instance)s: %(reason)s'),
                          {'instance': instance.name, 'reason': e},
                          instance=instance)

    def container_info(self, instance):
        """Returns basic information about a LXD container

        :param instance: nova instance object
        :return: LXD container information

        """
        LOG.debug('container_info called for instance', instance=instance)
        try:
            if not self.container_defined(instance.name, instance):
                msg = _('Instance is not found.. %s') % instance.name
                raise exception.InstanceNotFound(msg)

            client = self.get_session(instance.host)
            return client.container_info(instance.name)
        except lxd_exceptions.APIError as ex:
            msg = _('Failed to communicate with LXD API %(instance)s:'
                    ' %(reason)s') % {'instance': instance.name,
                                      'reason': ex}
            raise exception.NovaException(msg)
        except Exception as e:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Error from LXD during container_info'
                              '%(instance)s: %(reason)s'),
                          {'instance': instance.name, 'reason': e},
                          instance=instance)

    def container_defined(self, instance_name, instance):
        """Determine if the container exists

        :param instance_name: container anme
        :param instance: nova instance opbject
        :return: True if exists otherwise False

        """
        LOG.debug('container_defined for instance', instance=instance)
        try:
            client = self.get_session(instance.host)
            return client.container_defined(instance_name)
        except lxd_exceptions.APIError as ex:
            if ex.status_code == 404:
                return False
            else:
                msg = _('Failed to get container status: %s') % ex
                raise exception.NovaException(msg)
        except Exception as e:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Error from LXD during container_defined'
                              '%(instance)s: %(reason)s'),
                          {'instance': instance.name, 'reason': e},
                          instance=instance)

    def container_start(self, instance_name, instance):
        """Start an LXD container

        :param instance_name: name of container
        :param instance: nova instance object

        """
        LOG.debug('container_start called for instance', instance=instance)
        try:
            LOG.info(_LI('Starting instance %(instance)s with '
                         '%(image)s'), {'instance': instance.name,
                                        'image': instance.image_ref})
            # Start the container
            client = self.get_session(instance.host)

            # (chuck): Something wicked could happen between
            # container
            if not self.container_defined(instance_name, instance):
                msg = _('Instance is not found.. %s ') % instance.name
                raise exception.InstanceNotFound(msg)

            (state, data) = client.container_start(instance_name,
                                                   CONF.lxd.timeout)
            self.operation_wait(data.get('operation'), instance)

            LOG.info(_LI('Successfully started instance %(instance)s with'
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
                    _LE('Failed to start container %(instance)s: %(reason)s'),
                    {'instance': instance_name, 'reason': ex},
                    instance=instance)

    def container_stop(self, instance_name, host, instance):
        """Stops an LXD container

        :param instance_name: instance name
        :param host:  host where the container is running
        :param instance: nova instance object

        """
        LOG.debug('container_stop called for instance', instance=instance)
        try:
            if not self.container_defined(instance_name, instance):
                msg = _('Instance is not found..: %s') % instance.name
                raise exception.InstanceNotFound(msg)

            LOG.info(_LI('Stopping instance %(instance)s with'
                         '%(image)s'), {'instance': instance.name,
                                        'image': instance.image_ref})
            # Stop the container
            client = self.get_session(host)
            (state, data) = client.container_stop(instance_name,
                                                  CONF.lxd.timeout)
            self.operation_wait(data.get('operation'), instance)

            LOG.info(_LI('Successfully stopped instance %(instance)s with'
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
                    _LE('Failed to stop container %(instance)s: '
                        '%(reason)s'), {'instance': instance_name,
                                        'reason': ex})

    def container_reboot(self, instance):
        """Reboot a LXD container

        :param instance: nova instance object

        """
        LOG.debug('container_reboot called for instance', instance=instance)
        try:
            if not self.container_defined(instance.name, instance):
                msg = _('Instance is not found..: %s') % instance.name
                raise exception.InstanceNotFound(msg)

            LOG.info(_LI('Rebooting instance %(instance)s with'
                         '%(image)s'), {'instance': instance.name,
                                        'image': instance.image_ref})

            # Container reboot
            client = self.get_session(instance.host)
            (state, data) = client.container_reboot(instance.name,
                                                    CONF.lxd.timeout)
            self.operation_wait(data.get('operation'), instance)

            LOG.info(_LI('Successfully rebooted instance %(instance)s with'
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
                    _LE('Failed to reboot container %(instance)s: '
                        '%(reason)s'), {'instance': instance.name,
                                        'reason': ex}, instance=instance)

    def container_destroy(self, instance_name, host, instance):
        """Destroy a LXD container

        :param instance_name: container name
        :param host: container host
        :param instance: nova instance object

        """
        LOG.debug('container_destroy for instance', instance=instance)
        try:
            if not self.container_defined(instance_name, instance):
                return

            LOG.info(_LI('Destroying instance %(instance)s with'
                         '%(image)s'), {'instance': instance.name,
                                        'image': instance.image_ref})

            # Destroying container
            self.container_stop(instance_name, host, instance)

            client = self.get_session(host)
            (state, data) = client.container_destroy(instance_name)
            self.operation_wait(data.get('operation'), instance)

            LOG.info(_LI('Successfully destroyed instance %(instance)s with'
                         '%(image)s'), {'instance': instance.name,
                                        'image': instance.image_ref})
        except lxd_exceptions.APIError as ex:
            msg = _('Failed to communicate with LXD API %(instance)s:'
                    ' %(reason)s') % {'instance': instance.name,
                                      'reason': ex}
            raise exception.NovaException(msg)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Failed to destroy container %(instance)s: '
                              '%(reason)s'), {'instance': instance_name,
                                              'reason': ex})

    def container_pause(self, instance_name, instance):
        """Pause a LXD container

        :param instance_name: container name
        :param instance: nova instance object

        """
        LOG.debug('container_paused called for instance', instance=instance)
        try:
            if not self.container_defined(instance_name, instance):
                msg = _('Instance is not found. %s') % instance_name
                raise exception.InstanceNotFound(msg)

            LOG.info(_LI('Pausing instance %(instance)s with'
                         '%(image)s'), {'instance': instance_name,
                                        'image': instance.image_ref})

            client = self.get_session(instance.host)
            (state, data) = client.container_suspend(instance_name,
                                                     CONF.lxd.timeout)
            self.operation_wait(data.get('operation'), instance)

            LOG.info(_LI('Successfully paused instance %(instance)s with'
                         '%(image)s'), {'instance': instance_name,
                                        'image': instance.image_ref})
        except lxd_exceptions.APIError as ex:
            msg = _('Failed to communicate with LXD API %(instance)s:'
                    ' %(reason)s') % {'instance': instance_name,
                                      'reason': ex}
            raise exception.NovaException(msg)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(
                    _LE('Failed to pause container %(instance)s: '
                        '%(reason)s'),
                    {'instance': instance_name,
                     'reason': ex}, instance=instance)

    def container_unpause(self, instance_name, instance):
        """Unpause a LXD container

        :param instance_name: container name
        :param instance: nova instance object

        """
        LOG.debug('container_unpause called for instance', instance=instance)
        try:
            if not self.container_defined(instance_name, instance):
                msg = _('Instance is not found. %s') % instance_name
                raise exception.InstanceNotFound(msg)

            LOG.info(_LI('Unpausing instance %(instance)s with'
                         '%(image)s'), {'instance': instance.name,
                                        'image': instance.image_ref})

            client = self.get_session(instance.host)
            (state, data) = client.container_resume(instance_name,
                                                    CONF.lxd.timeout)
            self.operation_wait(data.get('operation'), instance)

            LOG.info(_LI('Successfully unpaused instance %(instance)s with'
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
                    _LE('Failed to unpause container %(instance)s: '
                        '%(reason)s'), {'instance': instance_name,
                                        'reason': ex})

    def container_init(self, config, instance, host):
        """Create a LXD container

        :param config: LXD container config as a dict
        :param instance: nova instance object
        :param host: host to create the container on

        """
        LOG.debug('container_init called for instance', instance=instance)
        try:
            LOG.info(_LI('Creating container %(instance)s with'
                         '%(image)s'), {'instance': instance.name,
                                        'image': instance.image_ref})

            client = self.get_session(host)
            (state, data) = client.container_init(config)
            operation = data.get('operation')
            self.operation_wait(operation, instance)
            status, data = self.operation_info(operation, instance)
            data = data.get('metadata')
            if not data['status_code'] == 200:
                raise exception.NovaException(data['metadata'])

            LOG.info(_LI('Successfully created container %(instance)s with'
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
                    _LE('Failed to create container %(instance)s: %(reason)s'),
                    {'instance': instance.name,
                     'reason': ex}, instance=instance)

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

    #
    # Operation methods
    #

    def operation_wait(self, operation_id, instance):
        """Waits for an operation to return 200 (Success)

        :param operation_id: The operation to wait for.
        """
        LOG.debug('wait_for_contianer for instance', instance=instance)
        try:
            client = self.get_session(instance.host)
            if not client.wait_container_operation(operation_id, 200, -1):
                msg = _('Container creation timed out')
                raise exception.NovaException(msg)
        except lxd_exceptions.APIError as ex:
            msg = _('Failed to communicate with LXD API %(instance)s:'
                    '%(reason)s') % {'instance': instance.image_ref,
                                     'reason': ex}
            LOG.error(msg)
            raise exception.NovaException(msg)
        except Exception as e:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Error from LXD during operation wait'
                              '%(instance)s: %(reason)s'),
                          {'instance': instance.image_ref, 'reason': e},
                          instance=instance)

    def operation_info(self, operation_id, instance):
        LOG.debug('operation_info called for instance', instance=instance)
        try:
            client = self.get_session(instance.host)
            return client.operation_info(operation_id)
        except lxd_exceptions.APIError as ex:
            msg = _('Failed to communicate with LXD API %(instance)s:'
                    '%(reason)s') % {'instance': instance.image_ref,
                                     'reason': ex}
            LOG.error(msg)
            raise exception.NovaException(msg)
        except Exception as e:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Error from LXD during operation_info '
                              '%(instance)s: %(reason)s'),
                          {'instance': instance.image_ref, 'reason': e},
                          instance=instance)
