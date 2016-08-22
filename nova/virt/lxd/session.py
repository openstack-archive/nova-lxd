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
from oslo_service import loopingcall
from oslo_utils import excutils

from pylxd.deprecated import api
from pylxd.deprecated import exceptions as lxd_exceptions

_ = i18n._
_LE = i18n._LE
_LI = i18n._LI

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
            LOG.exception(_LE('Connection to LXD failed'))
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
        LOG.debug('container_update called for instance', instance=instance)
        try:
            client = self.get_session()

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
            client = self.get_session()
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

    def container_config(self, instance):
        """Fetches the configuration of a given LXD container

        :param instance: nova instance object
        :return: dictionary represenation of a LXD container

        """
        LOG.debug('container_config called for instance', instance=instance)
        try:
            client = self.get_session()
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
            client = self.get_session()
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
            client = self.get_session()
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
            client = self.get_session()

            (state, data) = client.container_start(instance_name,
                                                   CONF.lxd.timeout)
            self.operation_wait(data.get('operation'), instance)

            LOG.info(_LI('Successfully started instance %(instance)s with'
                         ' %(image)s'), {'instance': instance.name,
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

    def container_stop(self, instance_name, instance):
        """Stops an LXD container

        :param instance_name: instance name
        :param instance: nova instance object

        """
        LOG.debug('container_stop called for instance', instance=instance)
        try:
            LOG.info(_LI('Stopping instance %(instance)s with'
                         ' %(image)s'), {'instance': instance.name,
                                         'image': instance.image_ref})
            # Stop the container
            client = self.get_session()
            (state, data) = client.container_stop(instance_name,
                                                  CONF.lxd.timeout)
            self.operation_wait(data.get('operation'), instance)

            LOG.info(_LI('Successfully stopped instance %(instance)s with'
                         ' %(image)s'), {'instance': instance.name,
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
            LOG.info(_LI('Rebooting instance %(instance)s with'
                         ' %(image)s'), {'instance': instance.name,
                                         'image': instance.image_ref})

            # Container reboot
            client = self.get_session()
            (state, data) = client.container_reboot(instance.name,
                                                    CONF.lxd.timeout)
            self.operation_wait(data.get('operation'), instance)

            LOG.info(_LI('Successfully rebooted instance %(instance)s with'
                         ' %(image)s'), {'instance': instance.name,
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

    def container_destroy(self, instance_name, instance):
        """Destroy a LXD container

        :param instance_name: container name
        :param instance: nova instance object

        """
        LOG.debug('container_destroy for instance', instance=instance)
        try:
            LOG.info(_LI('Destroying instance %(instance)s with'
                         ' %(image)s'), {'instance': instance.name,
                                         'image': instance.image_ref})

            # Destroying container
            self.container_stop(instance_name, instance)

            client = self.get_session()
            (state, data) = client.container_destroy(instance_name)
            self.operation_wait(data.get('operation'), instance)

            LOG.info(_LI('Successfully destroyed instance %(instance)s with'
                         ' %(image)s'), {'instance': instance.name,
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
            LOG.info(_LI('Pausing instance %(instance)s with'
                         ' %(image)s'), {'instance': instance_name,
                                         'image': instance.image_ref})

            client = self.get_session()
            (state, data) = client.container_suspend(instance_name,
                                                     CONF.lxd.timeout)
            self.operation_wait(data.get('operation'), instance)

            LOG.info(_LI('Successfully paused instance %(instance)s with'
                         ' %(image)s'), {'instance': instance_name,
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
            LOG.info(_LI('Unpausing instance %(instance)s with'
                         ' %(image)s'), {'instance': instance.name,
                                         'image': instance.image_ref})

            client = self.get_session()
            (state, data) = client.container_resume(instance_name,
                                                    CONF.lxd.timeout)
            self.operation_wait(data.get('operation'), instance)

            LOG.info(_LI('Successfully unpaused instance %(instance)s with'
                         ' %(image)s'), {'instance': instance.name,
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

    def container_init(self, config, instance, host=None):
        """Create a LXD container

        :param config: LXD container config as a dict
        :param instance: nova instance object
        :param host: perform initialization on perfered host

        """
        LOG.debug('container_init called for instance', instance=instance)
        try:
            LOG.info(_LI('Creating container %(instance)s with'
                         ' %(image)s'), {'instance': instance.name,
                                         'image': instance.image_ref})

            client = self.get_session(host=host)
            (state, data) = client.container_init(config)
            operation = data.get('operation')
            self.operation_wait(operation, instance, host=host)
            status, data = self.operation_info(operation, instance, host=host)
            data = data.get('metadata')
            if not data['status_code'] == 200:
                msg = data.get('err') or data['metadata']
                raise exception.NovaException(msg)

            LOG.info(_LI('Successfully created container %(instance)s with'
                         ' %(image)s'), {'instance': instance.name,
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
            client = self.get_session()
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
        :param instance: The nove instance
        :return: true if alias is created, false otherwise

        """
        LOG.debug('create_alias called for instance', instance=instance)
        try:
            client = self.get_session()
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
        :param instance: The nova instance

        """
        LOG.debug('upload_image called for instance', instance=instance)
        try:
            client = self.get_session()
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

    def operation_wait(self, operation_id, instance, host=None):
        """Waits for an operation to return 200 (Success)

        :param operation_id: The operation to wait for.
        :param instance: nova instace object
        """
        LOG.debug('wait_for_container for instance', instance=instance)
        try:
            client = self.get_session(host=host)
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

    def operation_info(self, operation_id, instance, host=None):
        LOG.debug('operation_info called for instance', instance=instance)
        try:
            client = self.get_session(host=host)
            return client.operation_info(operation_id)
        except lxd_exceptions.APIError as ex:
            msg = _('Failed to communicate with LXD API %(instance)s:'
                    ' %(reason)s') % {'instance': instance.image_ref,
                                      'reason': ex}
            LOG.error(msg)
            raise exception.NovaException(msg)
        except Exception as e:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Error from LXD during operation_info '
                              '%(instance)s: %(reason)s'),
                          {'instance': instance.image_ref, 'reason': e},
                          instance=instance)

    #
    # Profile methods
    #
    def profile_list(self):
        LOG.debug('profile_list called for instance')
        try:
            client = self.get_session()
            return client.profile_list()
        except lxd_exceptions.APIError as ex:
            msg = _('Failed to communicate with LXD API: %(reason)s') \
                % {'reason': ex}
            LOG.error(msg)
            raise exception.NovaException(msg)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Error from LXD during profile_list: '
                              '%(reason)s') % {'reason': ex})

    def profile_defined(self, instance_name, instance):
        """Validate if the profile is available on the LXD
           host

           :param instance: nova instance object
        """
        LOG.debug('profile_defined called for instance',
                  instance=instance)
        try:
            found = False
            if instance_name in self.profile_list():
                found = True
            return found
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
        :param instance: nova instance object
        """
        LOG.debug('profile_create called for instance',
                  instance=instance)
        try:
            if self.profile_defined(instance.name, instance):
                msg = _('Profile already exists %(instance)s') % \
                    {'instance': instance.name}
                raise exception.NovaException(msg)

            client = self.get_session()
            return client.profile_create(config)
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
            if not self.profile_defined(instance.name, instance):
                msg = _('Profile not found %(instance)s') % \
                    {'instance': instance.name}
                raise exception.NovaException(msg)

            client = self.get_session()
            return client.profile_update(instance.name, config)
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
            if not self.profile_defined(instance.name, instance):
                return

            client = self.get_session()
            return client.profile_delete(instance.name)
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

    #
    # Host Methods
    #
    def host_certificate(self, instance, host):
        LOG.debug('host_certificate called for instance', instance=instance)
        try:
            client = self.get_session(host)
            return client.get_host_certificate()
        except lxd_exceptions.APIError as ex:
            msg = _('Failed to communicate with LXD %(instance)s:'
                    ' %(reason)s') % {'instance': instance.name,
                                      'ex': ex}
            LOG.error(msg)

    def get_host_config(self, instance):
        LOG.debug('host_config called for instance', instance=instance)
        try:
            client = self.get_session()
            return client.host_config()['environment']
        except lxd_exceptions.APIError as ex:
            msg = _('Failed to communicate with LXD %(instance)s:'
                    ' %(reason)s') % {'instance': instance.name,
                                      'ex': ex}
            LOG.error(msg)

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
        LOG.debug('container_migrate called for instance', instance=instance)
        try:
            LOG.info(_LI('Migrating instance %(instance)s with '
                         '%(image)s'), {'instance': instance_name,
                                        'image': instance.image_ref})

            client = self.get_session()
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

    #
    # Snapshot methods
    #

    def container_move(self, old_name, config, instance):
        """Move a container from one host to another

        :param old_name: Old container name
        :param config:  Old container config
        :param instance: nova instance object
        :return:

        """
        LOG.debug('container_move called for instance', instance=instance)
        try:
            LOG.info(_LI('Moving container %(instance)s with '
                         '%(image)s'), {'instance': instance.name,
                                        'image': instance.image_ref})

            # Container move
            client = self.get_session()
            (state, data) = client.container_local_move(old_name, config)
            self.operation_wait(data.get('operation'), instance)

            LOG.info(_LI('Successfully moved container %(instance)s with '
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
                    _LE('Failed to move container %(instance)s: '
                        '%(reason)s'),
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
            client = self.get_session()
            (state, data) = client.container_snapshot_create(
                instance.name, snapshot)
            self.operation_wait(data.get('operation'), instance)

            LOG.info(_LI('Successfully snapshotted container %(instance)s with'
                         ' %(image)s'), {'instance': instance.name,
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
            client = self.get_session()
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
            client = self.get_session()
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
        :param instance: nova instance object
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
        client = self.get_session()
        (state, data) = client.operation_info(event_id)
        status_code = data['metadata']['status_code']

        if status_code == 200:
            raise loopingcall.LoopingCallDone()
        elif status_code == 400:
            msg = _('Snapshot failed')
            raise exception.NovaException(msg)
