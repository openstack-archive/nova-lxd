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
import time

import eventlet

from nova import context
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
from nclxd.nova.virt.lxd import container_image
from nclxd.nova.virt.lxd import container_utils
from nclxd.nova.virt.lxd import vif

_ = i18n._
_LE = i18n._LE
_LW = i18n._LW
_LI = i18n._LI

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
        self.container_image = container_image.LXDContainerImage()
        self.firewall_driver = container_firewall.LXDContainerFirewall()

        self.vif_driver = vif.LXDGenericDriver()

    def list_instances(self):
        return self.container_client.client('list', host=None)

    def spawn(self, context, instance, image_meta, injected_files,
              admin_password, network_info=None, block_device_info=None,
              need_vif_plugged=True, rescue=False):
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

        start = time.time()
        try:
            self.container_image.setup_image(context, instance, image_meta)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.exception(_LE('Upload image failed: %(e)s'),
                                  {'e': ex})

        try:
            self.create_container(context, instance, image_meta, injected_files, admin_password,
                                  network_info, block_device_info, rescue, need_vif_plugged)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.exception(_LE('Upload image failed: %(e)s'),
                                  {'e': ex})
        end = time.time()
        total = end - start
        LOG.debug('Creation took %s seconds to boot.' % total)

    def create_container(self, context, instance, image_meta, injected_files, admin_password,
                        network_info, block_device_info, rescue, need_vif_plugged):
        if not self.container_client.client('defined', instance=instance.uuid, host=instance.host):
            container_config = self.container_config.create_container(instance, injected_files,
                                        block_device_info, rescue)

            eventlet.spawn(self.container_utils.container_init,
                                        container_config,
                                        instance,
                                        instance.host).wait()

            self.start_container(container_config, instance, network_info, need_vif_plugged)

    def start_container(self, container_config, instance, network_info, need_vif_plugged):
        LOG.debug('Starting instance')

        if self.container_client.client('running', instance=instance.uuid,
                    host=instance.host):
            return

        timeout = CONF.vif_plugging_timeout
        # check to see if neutron is ready before
        # doing anything else
        if (self.container_client.client('defined', instance=instance.uuid,
            host=instance.host) and need_vif_plugged and
            utils.is_neutron() and timeout):
                events = self._get_neutron_events(network_info)
        else:
                events = []

        try:
            with self.virtapi.wait_for_instance_event(
                instance, events, deadline=timeout,
                error_callback=self._neutron_failed_callback):
                container_config = self.plug_vifs(
                    container_config, instance, network_info,
                    need_vif_plugged)
        except exception.VirtualInterfaceCreateException:
            LOG.info(_LW('Failed to connect networking to instance'))

        self.container_utils.container_start(instance.uuid, instance)

    def reboot(self, context, instance, network_info, reboot_type,
               block_device_info=None, bad_volumes_callback=None):
        LOG.debug('container reboot')
        return self.container_utils.container_reboot(instance.uuid, instance)

    def plug_vifs(self, container_config, instance, network_info, need_vif_plugged):
        for viface in network_info:
            container_config = self.container_config.configure_network_devices(
                container_config, instance, viface)
            if need_vif_plugged:
                self.vif_driver.plug(instance, viface)
        self._start_firewall(instance, network_info)
        return container_config

    def unplug_vifs(self, instance, network_info):
        for viface in network_info:
            self.vif_driver.plug(instance, viface)
        self._start_firewall(instance, network_info)

    def destroy(self, context, instance, network_info, block_device_info=None,
                destroy_disks=True, migrate_data=None):
        self.container_utils.container_destroy(instance.uuid, instance.host)
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
        if not self.container_client.client('defined', instance=instance.uuid,
                                           host=instance.host):
            return

        self.container_utils.container_stop(instance.uuid, instance)
        self._container_local_copy(instance)
        self.container_utils.container_destroy(instance.uuid, instance.host)

        self.spawn(context, instance, image_meta, injected_files=None,
              admin_password=None, network_info=network_info, block_device_info=None,
              need_vif_plugged=False, rescue=True)


    def _container_local_copy(self, instance):
        ''' Creating snasphot  '''
        container_snapshot = {
            'name': 'snap',
            'stateful': False
        }
        self.container_utils.container_snapshot(container_snapshot, instance)

        ''' Creating container copy '''
        container_copy = {
            "config": None,
            "name": "%s-backup" % instance.uuid,
            "profiles": None,
            "source": {
                 "source": "%s/snap" % instance.uuid,
                "type": "copy"
                }

        }
        self.container_utils.container_copy(container_copy, instance)


    def unrescue(self, instance, network_info):
        LOG.debug('Conainer unrescue')
        old_name = '%s-backup' % instance.uuid
        container_config = {
            'name': '%s' % instance.uuid
        }

        self.container_utils.container_move(old_name, container_config, instance)
        self.container_utils.container_destroy(instance.uuid, instance.host)

    def cleanup(self, context, instance, network_info, block_device_info=None,
                destroy_disks=True, migrate_data=None, destroy_vifs=True):
        LOG.debug('container cleanup')
        container_dir = self.container_dir.get_instance_dir(instance.uuid)
        if os.path.exists(container_dir):
            shutil.rmtree(container_dir)

    def get_info(self, instance):
        container_state = self.container_client.client(
            'state', instance=instance.uuid,
                                                       host=instance.host)
        return hardware.InstanceInfo(state=container_state,
                                     max_mem_kb=0,
                                     mem_kb=0,
                                     num_cpu=2,
                                     cpu_time_ns=0)

    def get_console_output(self, context, instance):
        LOG.debug('in console output')

        console_log = self.container_dir.get_console_path(instance.uuid)
        if not os.path.exists(console_log):
            return
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
