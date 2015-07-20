# Copyright 2011 Justin Santa Barbara
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
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import os
import shutil

from nova.compute import power_state
from nova import exception
from nova import i18n
from oslo_config import cfg
from oslo_log import log as logging
from pylxd import api
from pylxd import exceptions as lxd_exceptions

_ = i18n._

CONF = cfg.CONF
LOG = logging.getLogger(__name__)

LXD_POWER_STATES = {
    'RUNNING': power_state.RUNNING,
    'STOPPED': power_state.SHUTDOWN,
    'STARTING': power_state.NOSTATE,
    'STOPPING': power_state.SHUTDOWN,
    'ABORTING': power_state.CRASHED,
    'FREEZING': power_state.PAUSED,
    'FROZEN': power_state.SUSPENDED,
    'THAWED': power_state.PAUSED,
    'PENDING': power_state.NOSTATE,
    'Success': power_state.RUNNING,
    'UNKNOWN': power_state.NOSTATE
}


class LXDContainerDirectories(object):

    def __init__(self):
        self.base_dir = os.path.join(CONF.instances_path,
                                     CONF.image_cache_subdirectory_name)

    def get_base_dir(self):
        return self.base_dir

    def get_instance_dir(self, instance):
        return os.path.join(CONF.instances_path,
                            instance)

    def get_container_image(self, image_meta):
        return os.path.join(self.base_dir,
                            '%s.tar.gz' % image_meta.get('name'))

    def get_container_configdrive(self, instance):
        return os.path.join(CONF.instances_path,
                            instance,
                            'config-drive')

    def get_console_path(self, instance):
        return os.path.join(CONF.lxd.lxd_root_dir,
                            'lxc',
                            instance,
                            'console.log')

    def get_container_dir(self, instance):
        return os.path.join(CONF.lxd.lxd_root_dir,
                            'lxc',
                            instance)

    def get_container_rootfs(self, instance):
        return os.path.join(CONF.lxd.lxd_root_dir,
                            'lxc',
                            instance,
                            'rootfs')


class LXDContainerUtils(object):

    def __init__(self):
        self.lxd = api.API()
        self.container_dir = LXDContainerDirectories()

    def init_lxd_host(self, host):
        LOG.debug('Host check')
        try:
            if CONF.lxd.lxd_default_profile not in self.lxd.profile_list():
                msg = (_('Default LXD profile is not available - %s')
                       % CONF.lxd.lxd_default_profile)
                raise exception.HostNotFound(msg)

            if not self.lxd.host_ping():
                msg = _('Unable to connect to LXD daemon')
                raise exception.HostNotFound(msg)

            return True
        except lxd_exceptions.APIError as ex:
            msg = _('Unable to connect to LXD daemon: %s') % ex
            raise exception.HostNotFound(msg)

    def list_containers(self):
        try:
            return self.lxd.container_list()
        except lxd_exceptions.APIError as ex:
            msg = _('Unable to list instances: %s') % ex
            raise exception.NovaException(msg)

    def container_running(self, instance):
        LOG.debug('container running')
        return self.lxd.container_running(instance)

    def container_start(self, instance):
        LOG.debug('container start')
        try:
            return self.lxd.container_start(instance,
                                            CONF.lxd.lxd_timeout)
        except lxd_exceptions.APIError as ex:
            msg = _('Failed to start container: %s') % ex
            raise exception.NovaException(msg)

    def container_stop(self, instance):
        LOG.debug('container stop')
        try:
            return self.lxd.container_stop(instance,
                                           CONF.lxd.lxd_timeout)
        except lxd_exceptions.APIError as ex:
            if ex.status_code == 404:
                return
            else:
                msg = _('Failed to stop container: %s') % ex
                raise exception.NovaException(msg)

    def container_pause(self, instance):
        LOG.debug('container pause')
        try:
            return self.lxd.container_freeze(instance,
                                             CONF.lxd.lxd_timeout)
        except lxd_exceptions.APIError as ex:
            if ex.status_code == 404:
                return
            else:
                msg = _('Failed to pause container: %s') % ex
                raise exception.NovaException(msg)

    def container_unpause(self, instance):
        LOG.debug('container unpause')
        try:
            return self.lxd.container_unfreeze(instance,
                                               CONF.lxd.lxd_timeout)
        except lxd_exceptions.APIError as ex:
            if ex.status_code == 404:
                return
            else:
                msg = _('Failed to unpause container: %s') % ex
                raise exception.NovaException(msg)

    def container_destroy(self, instance):
        LOG.debug('Container destroy')
        try:
            return self.lxd.container_destroy(instance)
        except lxd_exceptions.APIError as ex:
            if ex.status_code == 404:
                return
            else:
                msg = _('Failed to destroy container: %s') % ex
                raise exception.NovaException(msg)

    def container_cleanup(self, instance, network_info, block_device_info):
        LOG.debug('continer cleanup')
        container_dir = self.container_dir.get_instance_dir(instance.name)
        if os.path.exists(container_dir):
            shutil.rmtree(container_dir)

    def container_info(self, instance):
        LOG.debug('container info')
        try:
            container_state = self.lxd.container_state(instance)
            state = LXD_POWER_STATES[container_state]
        except lxd_exceptions.APIError:
            state = power_state.NOSTATE
        return state

    def container_init(self, container_config):
        LOG.debug('container init')
        try:
            return self.lxd.container_init(container_config)
        except lxd_exceptions.APIError as ex:
            msg = _('Failed to destroy container: %s') % ex
            raise exception.NovaException(msg)

    def container_update(self, instance, config):
        LOG.debug('Updating container')
        try:
            return self.lxd.container_update(instance, config)
        except lxd_exceptions.APIError as ex:
            msg = _('Failed to update container: %s') % ex
            raise exception.NovaException(msg)

    def container_defined(self, instance):
        LOG.debug('container defined')
        try:
            return self.lxd.container_defined(instance)
        except lxd_exceptions.APIError as ex:
            msg = _('Failed to get container status: %s') % ex
            raise exception.NovaException(msg)

    def container_reboot(self, instance):
        try:
            return self.lxd.container_reboot(instance)
        except lxd_exceptions.APIError as ex:
            if ex.status_code == 404:
                pass
            else:
                msg = _('Failed to reboot container: %s') % ex
                raise exception.NovaException(msg)

    def wait_for_container(self, oid):
        if not oid:
            msg = _('Unable to determine container operation')
            raise exception.NovaException(msg)

        if not self.lxd.wait_container_operation(oid, 200, 20):
            msg = _('Container creation timed out')
            raise exception.NovaException(msg)
