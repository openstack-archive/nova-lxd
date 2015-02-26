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

import lxc

from oslo.config import cfg
from oslo_log import log as logging
from oslo.utils import units, excutils

from nova.i18n import _, _LW, _LE, _LI
from nova.openstack.common import log as logging
from nova import utils
from nova import exception
from nova.compute import power_state

from . import config
from . import utils as container_utils
from . import vif
from . import images

CONF = cfg.CONF
CONF.import_opt('use_cow_images', 'nova.virt.driver')
CONF.import_opt('vif_plugging_timeout', 'nova.virt.driver')
CONF.import_opt('vif_plugging_is_fatal', 'nova.virt.driver')
LOG = logging.getLogger(__name__)

MAX_CONSOLE_BYTES = 100 * units.Ki

LXD_POWER_STATES = {
    'RUNNING': power_state.RUNNING,
    'STOPPED': power_state.SHUTDOWN,
    'STARTING': power_state.BUILDING,
    'STOPPING': power_state.SHUTDOWN,
    'ABORTING': power_state.CRASHED,
    'FREEZING': power_state.PAUSED,
    'FROZEN': power_state.SUSPENDED,
    'THAWED': power_state.PAUSED,
    'NONE': power_state.NOSTATE
}

class Container(object):

    def __init__(self, client, virtapi, firewall):
        self.client = client
        self.virtapi = virtapi
        self.firewall_driver = firewall

        self.vif_driver = vif.LXDGenericDriver()

    def init_container(self):
        if not os.path.exists(CONF.lxd.lxd_socket):
            msg = _('LXD is not running.')
            raise Exception(msg)

    def get_console_log(self, instance):
        console_log = os.path.join(CONF.lxd.lxd_root_dir,
                                   instance['uuid'],
                                   'container.console')
	user = os.getuid()
	utils.execute('chown', user, console_log, run_as_root=True)
        with open(console_log, 'rb') as fp:
            log_data, remaining = utils.last_bytes(fp, MAX_CONSOLE_BYTES)
            if remaining > 0:
                LOG.info(_LI('Truncated console log returned, '
                             '%d bytes ignored'),
                         remaining, instance=instance)
        return log_data

    def start_container(self, context, instance, image_meta, injected_files,
                        admin_password, network_info, block_device_info, flavor):
        LOG.info(_LI('Starting new instance'), instance=instance)

        try:
            # Setup the LXC instance
            instance_name = instance['uuid']
            container = lxc.Container(instance_name)
            container.set_config_path(CONF.lxd.lxd_root_dir)

            ''' Fetch the image from glance '''
            self._fetch_image(context, instance, image_meta)

            ''' Set up the configuration file '''
            self._write_config(container, instance, network_info, image_meta)

            ''' Start the container '''
            self._start_container(context, instance, network_info, image_meta)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                self.destroy_container(context, instance, network_info,
                                       block_device_info)

    def destroy_container(self, context, instance, network_info, block_device_info,
                destroy_disks=None, migrate_data=None):
        self.client.stop(instance['uuid'])
        self.client.destroy(instance['uuid'])
        self.teardown_network(instance, network_info)

    def get_container_info(self, instance):
        instance_name = instance['uuid']
        container = lxc.Container(instance_name)
        container.set_config_path(CONF.lxd.lxd_root_dir)

        try:
            mem = int(container.get_cgroup_item('memory.usage_in_bytes')) / units.Mi
        except KeyError:
            mem = 0


        container_state = self.client.state(instance_name)
        if container_state is None:
                container_state = 'NONE'

        LOG.info(_('!!! %s') % container_state)
        return {'state': LXD_POWER_STATES[container_state],
                'mem': mem,
                'cpu': 1}


    def _fetch_image(self, context, instance, image_meta):
        image = images.ContainerImage(context, instance, image_meta)
        image.create_container()

    def _start_container(self, context, instance, network_info, image_meta):
        timeout = CONF.vif_plugging_timeout
        # check to see if neutron is ready before
        # doing anything else
        if (not self.client.running(instance['uuid']) and
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

        self.client.start(instance['uuid'])

    def _write_config(self, container, instance, network_info, image_meta):
        self.config = config.LXDSetConfig(container, instance,
                                          image_meta, network_info)
        self.config.write_config()

    def _start_network(self, instance, network_info):
        for vif in network_info:
            self.vif_driver.plug(instance, vif)

    def teardown_network(self, instance, network_info):
        for vif in network_info:
            self.vif_driver.unplug(instance, vif)
        self._stop_firewall(instance, network_info)

    def _start_firewall(self, instance, network_info):
        self.firewall_driver.setup_basic_filtering(instance, network_info)
        self.firewall_driver.prepare_instance_filter(instance, network_info)
        self.firewall_driver.apply_instance_filter(instance, network_info)

    def _stop_firewall(self, instance, network_info):
        self.firewall_driver.unfilter_instance(instance, network_info)

    def _get_neutron_events(self, network_info):
        return [('network-vif-plugged', vif['id'])
                for vif in network_info if vif.get('active', True) is False]

    def _neutron_failed_callback(self, event_name, instance):
        LOG.error(_LE('Neutron Reported failure on event '
                      '%(event)s for instance %(uuid)s'),
                  {'event': event_name, 'uuid': instance.uuid})
        if CONF.vif_plugging_is_fatal:
            raise exception.VirtualInterfaceCreateException()
