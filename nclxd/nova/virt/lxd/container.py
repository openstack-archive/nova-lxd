# Copyright (c) 2015 Canonical Ltd
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

from oslo.config import cfg
from oslo_log import log as logging

from nova.i18n import _, _LW, _LE, _LI
from nova import utils
from nova import exception

from . import vif
from . import images
from . import constants
from . import config

CONF = cfg.CONF
CONF.import_opt('vif_plugging_timeout', 'nova.virt.driver')
CONF.import_opt('vif_plugging_is_fatal', 'nova.virt.driver')

LOG = logging.getLogger(__name__)


class Container(object):

    def __init__(self, client):
        self.client = client
        self.image = images.ContainerImage(self.client)
        self.config = config.ContainerConfig(self.client)
        self.vif_driver = vif.LXDGenericDriver()

    def init_host(self):
        host = self.client.ping()
        if host['status'] != 'Success':
            raise Exception('LXD is not running')

    def start_container(self, context, instance, image_meta, injected_files,
                        admin_password, network_info=None, block_device_info=None,
                        flavor=None):
        LOG.debug(_('Fetching image from Glance.'))
        self.image.fetch_image(context, instance, image_meta)

        LOG.debug(_('Writing LXD config'))
        self.config.create_container_config(instance, image_meta, network_info)

        LOG.debug(_('Setup Networking'))
        self._start_network(instance, network_info)

        LOG.debug(_('Start container'))
        #self._start_container(instance)

    def container_destroy(self, context, instance, network_info, block_device_info,
                destroy_disks, migrate_data):
        timeout = CONF.vif_plugging_timeout
        # check to see if neutron is ready before
        # doing anything else
        if (not self.client.running(instance.uuid) and
                utils.is_neutron() and timeout):
            events = self._get_neutron_events(network_info)
        else:
            events = {}

        try:
            with self.virtapi.wait_for_instance_event(
                    instance, events, deadline=timeout,
                    error_callback=self._neutron_failed_callback):
                self._start_network(instance, network_info)
                self._start_firewall(instance, network_info)
        except exception.VirtualInterfaceCreateException:
            LOG.info(_LW('Failed'))
        try:
            (status, resp) = self.client.container_delete(instance.uuid)
            if resp.get('status') != 'OK':
                raise exception.NovaException
        except Exception as e:
            LOG.debug(_('Failed to delete instance: %s') % resp.get('metadata'))
            msg = _('Cannot delete container: {0}')
            raise exception.NovaException(msg.format(e),
                                          instance_id=instance.name)

    def _start_container(self, instance):
        try:
            (status, resp) = self.client.container_start(instance.uuid)
            if resp.get('status') != 'OK':
                raise exception.NovaException
        except Exception as e:
            LOG.debug(_('Failed to delete instance: %s') % resp.get('metadata'))
            msg = _('Cannot delete container: {0}')
            raise exception.NovaException(msg.format(e),
                                          instance_id=instance.name)

    def _start_network(self, instance, network_info):
         for vif in network_info:
            self.vif_driver.plug(instance, vif)

    def _teardown_network(self, instance, network_info):
        for vif in network_info:
            self.vif_driver.unplug(instance, vif)

    def _get_neutron_events(self, network_info):
        return [('network-vif-plugged', vif['id'])
                for vif in network_info if vif.get('active', True) is False]

    def _neutron_failed_callback(self, event_name, instance):
        LOG.error(_LE('Neutron Reported failure on event '
                      '%(event)s for instance %(uuid)s'),
                  {'event': event_name, 'uuid': instance.uuid})
        if CONF.vif_plugging_is_fatal:
            raise exception.VirtualInterfaceCreateException()