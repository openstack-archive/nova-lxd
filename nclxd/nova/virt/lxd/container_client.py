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

from nova import exception
from nova import i18n
from nova.compute import power_state
from oslo_config import cfg
from oslo_log import log as logging

from pylxd import api
from pylxd import exceptions as lxd_exceptions

from nclxd.nova.virt.lxd import constants
from nclxd.nova.virt.lxd import container_utils

_ = i18n._

CONF = cfg.CONF
LOG = logging.getLogger(__name__)

class LXDContainerClient(object):

    def __init__(self):
        self.container_dir = container_utils.LXDContainerDirectories()

    def client(self, func, *args, **kwargs):
        if kwargs['host'] is None:
            lxd_client = api.API()
        else:
            try:
                lxd_client = api.API(host=kwargs['host'])
            except lxd_exceptions.APIError as ex:
                msg = ('Unable to connect to %s %s') % (kwargs['host'],
                                                        ex)
                raise exception.NovaException(msg)
        func = getattr(self, "container_%s" % func)
        return func(lxd_client, *args, **kwargs)

    def container_list(self, lxd, *args, **kwargs):
        try:
            return lxd.container_list()
        except lxd_exceptions.APIError as ex:
            msg = _('Unable to list instances: %s') % ex
            raise exception.NovaException(msg)

    def container_running(self, lxd, *args, **kwargs):
        LOG.debug('container running')
        try:
            return lxd.container_running(kwargs['instance'])
        except lxd_exceptions.APIError as ex:
            msg = _('Failed to start container: %s') % ex
            raise exception.NovaException(msg)

    def container_start(self, lxd, *args, **kwargs):
        LOG.debug('container start')
        try:
            return lxd.container_start(kwargs['instance'],
                                            CONF.lxd.timeout)
        except lxd_exceptions.APIError as ex:
            msg = _('Failed to start container: %s') % ex
            raise exception.NovaException(msg)

    def container_stop(self, lxd, *args, **kwargs):
        LOG.debug('container stop')
        try:
            return lxd.container_stop(kwargs['instance'],
                                           CONF.lxd.timeout)
        except lxd_exceptions.APIError as ex:
            if ex.status_code == 404:
                return
            else:
                msg = _('Failed to stop container: %s') % ex
                raise exception.NovaException(msg)

    def container_pause(self, lxd, *args, **kwargs):
        LOG.debug('container pause')
        try:
            return lxd.container_suspend(kwargs['instance'],
                                         CONF.lxd.timeout)
        except lxd_exceptions.APIError as ex:
            if ex.status_code == 404:
                return
            else:
                msg = _('Failed to pause container: %s') % ex
                raise exception.NovaException(msg)

    def container_unpause(self, lxd, *args, **kwargs):
        LOG.debug('container unpause')
        try:
            return lxd.container_resume(kwargs['instance'],
                                        CONF.lxd.timeout)
        except lxd_exceptions.APIError as ex:
            if ex.status_code == 404:
                return
            else:
                msg = _('Failed to unpause container: %s') % ex
                raise exception.NovaException(msg)

    def container_destroy(self, lxd, *args, **kwargs):
        LOG.debug('Container destroy')
        try:
            return lxd.container_destroy(kwargs['instance'])
        except lxd_exceptions.APIError as ex:
            if ex.status_code == 404:
                return
            else:
                msg = _('Failed to destroy container: %s') % ex
                raise exception.NovaException(msg)

    def container_state(self, lxd, *args, **kwargs):
        LOG.debug('container state')
        try:
            (state, data) = lxd.container_state(kwargs['instance'])
            state = constants.LXD_POWER_STATES[data['metadata']['status_code']]
        except lxd_exceptions.APIError:
            state = power_state.NOSTATE
        return state

    def container_info(self, lxd, *args, **kwargs):
        LOG.debug('container info')
        try:
            return lxd.container_info(kwargs['instance'])
        except lxd_exceptions.APIError as ex:
            msg = _('Failed to retrieve container info: %s') % ex
            raise exception.NovaException(msg)

    def container_init(self, lxd, *args, **kwargs):
        LOG.debug('container init')
        try:
            return lxd.container_init(kwargs['container_config'])
        except lxd_exceptions.APIError as ex:
            msg = _('Failed to init container: %s') % ex
            raise exception.NovaException(msg)

    def container_update(self, lxd, *args, **kwargs):
        LOG.debug('Updating container')
        try:
            return lxd.container_update(kwargs['instance'],
                                             kwargs['container_config'])
        except lxd_exceptions.APIError as ex:
            msg = _('Failed to update container: %s') % ex
            raise exception.NovaException(msg)

    def container_defined(self, lxd, *args, **kwargs):
        LOG.debug('container defined')
        try:
            return lxd.container_defined(kwargs['instance'])
        except lxd_exceptions.APIError as ex:
            if ex.status_code == 404:
                return False
            else:
                msg = _('Failed to get container status: %s') % ex
                raise exception.NovaException(msg)

    def container_reboot(self, lxd, *args, **kwargs):
        try:
            return lxd.container_reboot(kwargs['instance'])
        except lxd_exceptions.APIError as ex:
            if ex.status_code == 404:
                pass
            else:
                msg = _('Failed to reboot container: %s') % ex
                raise exception.NovaException(msg)

    def container_config(self, lxd, *args, **kwargs):
        try:
            return lxd.get_container_config(kwargs['instance'])
        except lxd_exceptions.APIError as ex:
            msg = _('Failed to fetch container config: %s') % ex
            raise exception.NovaException(msg)

    def container_migrate(self, lxd, *args, **kwargs):
        try:
            return lxd.container_migrate(kwargs['instance'])
        except lxd_exceptions.APIError as ex:
            msg = _('Failed to migrate container: %s') % ex
            raise exception.NovaException(msg)

    def container_wait(self, lxd, *args, **kwargs):
        if not kwargs['oid']:
            msg = _('Unable to determine container operation')
            raise exception.NovaException(msg)

        if not lxd.wait_container_operation(kwargs['oid'], 200, -1):
            msg = _('Container creation timed out')
            raise exception.NovaException(msg)

    # container images
    def container_image_defined(self, lxd, *args, **kwargs):
        try:
            return lxd.image_defined(kwargs['instance'])
        except lxd_exceptions.APIError as ex:
            if ex.status_code == 404:
                return False
            else:
                msg = _('Failed to determine image: %s') % ex
                raise exception.NovaException(msg)

    def container_alias_defined(self, lxd, *args, **kwargs):
        try:
            return lxd.alias_defined(kwargs['instance'])
        except lxd_exceptions.APIError as ex:
            if ex.status_code == 404:
                return False
            else:
                msg = _('Failed to determine alias: %s') % ex
                raise exception.NovaException(msg)

    # operations
    def container_operation_info(self, lxd, *args, **kwargs):
        try:
            return lxd.operation_info(kwargs['oid'])
        except lxd_exceptions.APIError as ex:
            msg = _('Failed to migrate container: %s') % ex
            raise exception.NovaException(msg)
