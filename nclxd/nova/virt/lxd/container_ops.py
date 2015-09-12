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
import pwd
import shutil

from nova import exception
from nova import i18n
from nova import utils
from nova.compute import vm_states
from nova.virt import configdrive
from nova.virt import driver
from nova.virt import hardware
from oslo_config import cfg
from oslo_log import log as logging
from oslo_service import loopingcall
from oslo_utils import excutils
from oslo_utils import units

from nclxd.nova.virt.lxd import container_config
from nclxd.nova.virt.lxd import container_client
from nclxd.nova.virt.lxd import container_firewall
from nclxd.nova.virt.lxd import container_utils
from nclxd.nova.virt.lxd import vif

_ = i18n._
_LE = i18n._LE
_LW = i18n._LW
_LI= i18n._LI

CONF = cfg.CONF
CONF.import_opt('vif_plugging_timeout', 'nova.virt.driver')
CONF.import_opt('vif_plugging_is_fatal', 'nova.virt.driver')
LOG = logging.getLogger(__name__)

MAX_CONSOLE_BYTES = 100 * units.Ki

class LXDContainerOperations(object):

    def __init__(self, virtapi):
        self.virtapi = virtapi

        self.container_config = container_config.LXDContainerConfig()
        self.container_client = container_client.LXDContainerClient()
        self.container_dir = container_utils.LXDContainerDirectories()
        self.container_utils = container_utils.LXDContainerUtils()
        self.firewall_driver = container_firewall.LXDContainerFirewall()

        self.vif_driver = vif.LXDGenericDriver()

    def list_instances(self):
        return self.container_client.client('list', host=None)

    def spawn(self, context, instance, image_meta, injected_files,
              admin_password, network_info=None, block_device_info=None,
              name_label=None, rescue=False):
        msg = ('Spawning container '
               'network_info=%(network_info)s '
               'image_meta=%(image_meta)s '
               'instance=%(instance)s '
               'block_device_info=%(block_device_info)s' %
               {'network_info': network_info,
                'instance': instance,
                'image_meta': image_meta,
                'block_device_info': block_device_info})
        LOG.debug(msg, instance=instance)

        name = instance.uuid
        if rescue:
            name = name_label

        if self.container_client.client('defined', instance=name, host=instance.host):
            raise exception.InstanceExists(name=name)

        container_config = self.container_config.create_container(context, instance, image_meta,
                             injected_files, admin_password, network_info,
                             block_device_info, name_label, rescue)

        self.start_instance(container_config, instance, network_info, rescue)

    def start_instance(self, container_config, instance, network_info, rescue=False):
        LOG.debug('Staring instance')
        name = instance.uuid
        if rescue:
            name = '%s-rescue' % instance.uuid

        timeout = CONF.vif_plugging_timeout
        # check to see if neutron is ready before
        # doing anything else
        if (self.container_client.client('defined', instance=name,
                                             host=instance.host) and
                utils.is_neutron() and timeout):
            events = self._get_neutron_events(network_info)
        else:
            events = []

        try:
            with self.virtapi.wait_for_instance_event(
                    instance, events, deadline=timeout,
                    error_callback=self._neutron_failed_callback):
                container_config = self.plug_vifs(container_config, instance, network_info)
        except exception.VirtualInterfaceCreateException:
            LOG.info(_LW('Failed to connect networking to instance'))

        self.container_utils.container_start(name, instance)

    def reboot(self, context, instance, network_info, reboot_type,
               block_device_info=None, bad_volumes_callback=None):
        LOG.debug('container reboot')
        return self.container_utils.container_reboot(instance.uuid, instance)

    def plug_vifs(self, container_config, instance, network_info):
        for viface in network_info:
            container_config = self.container_config.configure_network_devices(
                    container_config, instance, viface)
            self.vif_driver.plug(instance, viface)
        self._start_firewall(instance, network_info)
        return container_config

    def unplug_vifs(self, instance, network_info):
        for viface in network_info:
            self.vif_driver.plug(instance, viface)
        self._start_firewall(instance, network_info)

    def destroy(self, context, instance, network_info, block_device_info=None,
                destroy_disks=True, migrate_data=None):
        self.container_utils.container_destroy(instance.uuid, instance)
        self.cleanup(context, instance, network_info, block_device_info)

    def power_off(self, instance, timeout=0, retry_interval=0):
        return self.container_utils.container_stop(instance.uuid, instance)

    def power_on(self, context, instance, network_info,
                 block_device_info=None):
        return self.container_utils.container_start(instance.uuid, instance)

    def pause(self, instance):
        return self.container_utils.container_pause(instance.uuid, instance)

    def unpause(self, instance):
        return self.container_utils.container_unpause(instance.uuid, instance)

    def suspend(self, context, instance):
        return self.container_utils.container_pause(instance.uuid, instance)


    def resume(self, context, instance, network_info, block_device_info=None):
        return self.container_utils.container_unpause(instance.uuid, instance)


    def rescue(self, context, instance, network_info, image_meta,
               rescue_password):
        LOG.debug('Container rescue')
        self.container_client.client('stop', instance=instance.uuid,
                                     host=instance.host)
        rescue_name_label = '%s-rescue' % instance.uuid
        if self.container_client.client('defined', instance=rescue_name_label,
                                        host=instance.host):
            msg = _('Instace is arleady in Rescue mode: %s') % instance.uuid
            raise exception.NovaException(msg)
        self.spawn(context, instance, image_meta, [], rescue_password,
                   network_info, name_label=rescue_name_label, rescue=True)

    def unrescue(self, instance, network_info):
        LOG.debug('Conainer unrescue')
        self.container_client.client('start', instance=instance.uuid,
                                      host=instance.host)
        rescue = '%s-rescue' % instance.uuid
        self.container_client.client('destroy', instance=instance.uuid,
                                     host=instance.host)

    def cleanup(self, context, instance, network_info, block_device_info=None,
                destroy_disks=True, migrate_data=None, destroy_vifs=True):
        LOG.debug('container cleanup')
        container_dir = self.container_dir.get_instance_dir(instance.uuid)
        if os.path.exists(container_dir):
            shutil.rmtree(container_dir)

    def get_info(self, instance):
        container_state = self.container_client.client('state', instance=instance.uuid,
                                                       host=instance.host)
        return hardware.InstanceInfo(state=container_state,
                                     max_mem_kb=0,
                                     mem_kb=0,
                                     num_cpu=2,
                                     cpu_time_ns=0)

    def get_console_output(self, context, instance):
        LOG.debug('in console output')

        console_log = self.container_dir.get_console_path(instance.uuid)
        uid = pwd.getpwuid(os.getuid()).pw_uid
        utils.execute('chown', '%s:%s' % (uid, uid),
                      console_log, run_as_root=True)
        utils.execute('chmod', '755',
                      self.container_dir.get_container_dir(instance.uuid),
                      run_as_root=True)
        with open(console_log, 'rb') as fp:
            log_data, remaning = utils.last_bytes(fp,
                                                  MAX_CONSOLE_BYTES)
            return log_data

    def container_attach_interface(self, instance, image_meta, vif):
        try:
            self.vif_driver.plug(instance, vif)
            self.firewall_driver.setup_basic_filtering(instance, vif)
            container_config = (
                self.container_config.configure_container_net_device(instance,
                                                                     vif))
            self.container_client.client('update', instance=instance.uuid,
                                                   container_config=container_config,
                                                   host=instance.host)
        except exception.NovaException:
            self.vif_driver.unplug(instance, vif)

    def container_detach_interface(self, instance, vif):
        try:
            self.vif_driver.unplug(instance, vif)
        except exception.NovaException:
            pass

    def _get_neutron_events(self, network_info):
        return [('network-vif-plugged', vif['id'])
                for vif in network_info if vif.get('active', True) is False]

    def _neutron_failed_callback(self, event_name, instance):
        LOG.error(_LE('Neutron Reported failure on event '
                      '%(event)s for instance %(uuid)s'),
                  {'event': event_name, 'uuid': instance.uuid})
        if CONF.vif_plugging_is_fatal:
            raise exception.VirtualInterfaceCreateException()

    def _start_firewall(self, instance, network_info):
        self.firewall_driver.setup_basic_filtering(instance, network_info)
        self.firewall_driver.prepare_instance_filter(instance, network_info)
        self.firewall_driver.apply_instance_filter(instance, network_info)

    def _stop_firewall(self, instance, network_info):
        self.firewall_driver.unfilter_instance(instance, network_info)

    def _wait_for_active(self, operation_id, instance):
        instance.refresh()

        (state, data) = self.container_client.client('operation_info',
                        oid=operation_id, host=instance.host)
        operation_status = data['metadata']['status_code']
        if operation_status in [200, 202]:
            instance.vm_state = vm_states.ACTIVE
            instance.save()
            raise loopingcall.LoopingCallDone()
        elif operation_status in [400, 401]:
            instance.vm_state = vm_states.ERROR
            instance.save()
            raise loopingcall.LoopingCallDone()

