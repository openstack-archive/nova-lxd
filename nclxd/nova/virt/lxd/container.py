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
import pwd

from oslo.config import cfg
from oslo_log import log as logging
from oslo_utils import units

from nova.openstack.common import loopingcall

from nova.i18n import _, _LW, _LE
from nova import utils
from nova import exception
from nova.compute import power_state


from . import vif
from . import images

CONF = cfg.CONF
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
    'PENDING': power_state.BUILDING,
    'UNKNOWN': power_state.NOSTATE
}


class Container(object):

    def __init__(self, client, virtapi, firewall):
        self.client = client
        self.virtapi = virtapi
        self.firewall = firewall
        self.image = images.ContainerImage(self.client)
        self.vif_driver = vif.LXDGenericDriver()

    def init_host(self):
        (status, resp) = self.client.ping()
        if resp['status'] != 'Success':
            msg = _('LXD is not available')
            raise exception.HypervisorUnavailable(msg)

    def container_start(self, context, instance, image_meta, injected_files,
                        admin_password, network_info=None, block_device_info=None,
                        flavor=None):
        LOG.debug(_('Fetching image from Glance.'))
        self.image.fetch_image(context, instance, image_meta)

        LOG.debug(_('Setting up container profiles'))
        self.setup_container(instance, network_info)

        LOG.debug(_('Setup Networking'))
        self._start_network(instance, network_info)

        LOG.debug(_('Start container'))
        self._start_container(instance, network_info)

        LOG.debug(_('Start firewall'))
        self._start_firewall(instance, network_info)

    def setup_container(self, instance, network_info):
        console_log = self._get_console_path(instance)
        container_log = self._get_container_log(instance)
        container = {'name': instance.uuid,
                     'source': {'type': 'image', 'alias': instance.image_ref}}
        try:
            (status, resp) = self.client.container_init(container)
            if resp.get('status') != 'OK':
                raise exception.NovaException
        except Exception as e:
            LOG.debug(_('Failed to init container: %s') % resp)
            msg = _('Cannot init container: {0}')
            raise exception.NovaException(msg.format(e),
                                          instance_id=instance.name)

        oid = resp.get('operation').split('/')[3]
        if not oid:
            msg = _('Unable to determine resource id')
            raise exception.NovaException(msg)

        timer = loopingcall.FixedIntervalLoopingCall(self._wait_for_start,
                                                     oid)
        timer.start(interval=0.5).wait()

        network_type = self._get_container_devices(network_info)
        container_config = {'config': {'raw.lxc': 'lxc.logfile = %s\nlxc.console.logfile=%s\n'
                                                  % (container_log, console_log)},
                            'devices': {'eth0': {'nictype': 'bridged',
                                                 'parent': network_type['parent'],
                                                 'hwaddr': network_type['hwaddr'],
                                                 'type': 'nic'}}}
        try:
            (status, resp) = self.client.container_update(
                instance.uuid, container_config)
            if resp.get('status') != 'OK':
                raise exception.NovaException
        except Exception as e:
            LOG.debug(_('Failed to update container: %s') % resp)
            msg = _('Cannot update container: {0}')
            raise exception.NovaException(msg.format(e),
                                          instance_id=instance.name)

    def container_restart(self, context, instance, network_info, reboot_type,
                          block_device_info=None, bad_volumes_callback=None):
        try:
            (status, resp) = self.client.container_restart(instance.uuid)
            if resp.get('status') != 'OK':
                raise exception.NovaException
        except Exception as e:
            LOG.debug(_('Failed to restart container: %s') % resp)
            msg = _('Cannot restart container: {0}')
            raise exception.NovaException(msg.format(e),
                                          instance_id=instance.name)

    def container_power_on(self, instance, shutdown_timeout=0, shutdown_attempts=0):
        try:
            (status, resp) = self.client.container_stop(instance.uuid)
            if resp.get('status') != 'OK':
                raise exception.NovaException
        except Exception as e:
            LOG.debug(_('Failed to power on container: %s') % resp)
            msg = _('Cannot power on container: {0}')
            raise exception.NovaException(msg.format(e),
                                          instance_id=instance.name)

    def container_power_off(self, instance):
        try:
            (status, resp) = self.client.container_stop(instance.uuid)
            if resp.get('status') != 'OK':
                raise exception.NovaException
        except Exception as e:
            LOG.debug(_('Failed to power off container: %s') % resp)
            msg = _('Cannot power on  container: {0}')
            raise exception.NovaException(msg.format(e),
                                          instance_id=instance.name)

    def container_suspend(self, instance):
        try:
            (status, resp) = self.client.container_suspend(instance.uuid)
            if resp.get('status') != 'OK':
                raise exception.NovaException
        except Exception as e:
            LOG.debug(_('Failed to suspend container: %s') % resp)
            msg = _('Cannot suspend container: {0}')
            raise exception.NovaException(msg.format(e),
                                          instance_id=instance.name)

    def container_resume(self, context, instance, network_info, block_device_info=None):
        try:
            (status, resp) = self.client.container_resume(instance.uuid)
            if resp.get('status') != 'OK':
                raise exception.NovaException
        except Exception as e:
            LOG.debug(_('Failed to resume container: %s') % resp)
            msg = _('Cannot suspend container: {0}')
            raise exception.NovaException(msg.format(e),
                                          instance_id=instance.name)

    def container_destroy(
        self, context, instance, network_info, block_device_info,
                destroy_disks, migrate_data):
        try:
            (status, resp) = self.client.container_delete(instance.uuid)
            if resp.get('status') != 'OK':
                raise exception.NovaException
        except Exception as e:
            LOG.debug(_('Failed to delete instance: %s') %
                      resp.get('metadata'))
            msg = _('Cannot delete container: {0}')
            raise exception.NovaException(msg.format(e),
                                          instance_id=instance.name)
        self._stop_firewall(instance, network_info)

    def get_console_log(self, instance):
        console_dir = os.path.join(CONF.lxd.lxd_root_dir, instance.uuid)
        console_log = self._get_console_path(instance)
        uid = pwd.getpwuid(os.getuid()).pw_uid
        utils.execute('chown', '%s:%s' %
                      (uid, uid), console_log, run_as_root=True)
        utils.execute('chmod', '755', console_dir, run_as_root=True)
        with open(console_log, 'rb') as fp:
            log_data, remaining = utils.last_bytes(fp, MAX_CONSOLE_BYTES)
            if remaining > 0:
                LOG.info(_('Truncated console log returned, '
                           '%d bytes ignored'),
                         remaining, instance=instance)
        return log_data

    def container_info(self, instance):
        try:
            (status, resp) = self.client.container_info(instance.uuid)
            metadata = resp.get('metadata')
            container_state = metadata['status']['status']
            state = LXD_POWER_STATES[container_state]
        except Exception:
            state = power_state.NOSTATE
        return state

    def _start_container(self, instance, network_info):
        timeout = CONF.vif_plugging_timeout
        # check to see if neutron is ready before
        # doing anything else
        if (not self.client.container_running(instance.uuid) and
                utils.is_neutron() and timeout):
            events = self._get_neutron_events(network_info)
        else:
            events = {}

        try:
            with self.virtapi.wait_for_instance_event(
                instance, events, deadline=timeout,
                    error_callback=self._neutron_failed_callback):
                self._start_network(instance, network_info)
        except exception.VirtualInterfaceCreateException:
            LOG.info(_LW('Failed'))

        try:
            (status, resp) = self.client.container_start(instance.uuid)
            if resp.get('status') != 'OK':
                raise exception.NovaException
        except Exception as e:
            LOG.debug(_('Failed to container instance: %s') %
                      resp.get('metadata'))
            msg = _('Cannot container container: {0}')
            raise exception.NovaException(msg.format(e),
                                          instance_id=instance.name)

    def _start_network(self, instance, network_info):
        for vif in network_info:
            self.vif_driver.plug(instance, vif)

    def _teardown_network(self, instance, network_info):
        for vif in network_info:
            self.vif_driver.unplug(instance, vif)

    def _wait_for_start(self, oid):
        containers = self.client.operation_list()
        if oid not in containers:
            raise loopingcall.LoopingCallDone()

    def _get_neutron_events(self, network_info):
        return [('network-vif-plugged', vif['id'])
                for vif in network_info if vif.get('active', True) is False]

    def _neutron_failed_callback(self, event_name, instance):
        LOG.error(_LE('Neutron Reported failure on event '
                      '%(event)s for instance %(uuid)s'),
                  {'event': event_name, 'uuid': instance.uuid})
        if CONF.vif_plugging_is_fatal:
            raise exception.VirtualInterfaceCreateException()

    def _get_console_path(self, instance):
        return os.path.join(CONF.lxd.lxd_root_dir, instance.uuid, 'console.log')

    def _get_container_log(self, instance):
        return os.path.join(CONF.lxd.lxd_root_dir, instance.uuid, 'container.log')

    def _get_container_devices(self, network_info):
        for vif in network_info:
            vif_id = vif['id'][:11]
            vif_type = vif['type']
            bridge = vif['network']['bridge']
            mac = vif['address']

        if vif_type == 'ovs':
            bridge = 'qbr%s' % vif_id

        return {
            'type': 'nic',
            'parent': bridge,
            'hwaddr': mac,
        }

    def _start_firewall(self, instance, network_info):
        self.firewall.setup_basic_filtering(instance, network_info)
        self.firewall.prepare_instance_filter(instance, network_info)
        self.firewall.apply_instance_filter(instance, network_info)

    def _stop_firewall(self, instance, network_info):
        self.firewall_driver.unfilter_instance(instance, network_info)

