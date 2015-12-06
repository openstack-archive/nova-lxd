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

from nova.virt import hardware
import os
import pwd
import shutil
import time

import eventlet
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import units

from nova import exception
from nova import i18n
from nova import utils

from nova_lxd.nova.virt.lxd import container_config
from nova_lxd.nova.virt.lxd import container_firewall
from nova_lxd.nova.virt.lxd import image
from nova_lxd.nova.virt.lxd.session import session
from nova_lxd.nova.virt.lxd import utils as container_dir
from nova_lxd.nova.virt.lxd import vif

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
        self.container_dir = container_dir.LXDContainerDirectories()
        self.image = image.LXDContainerImage()
        self.firewall_driver = container_firewall.LXDContainerFirewall()
        self.session = session.LXDAPISession()

        self.vif_driver = vif.LXDGenericDriver()

    def list_instances(self):
        return self.session.container_list()

    def spawn(self, context, instance, image_meta, injected_files,
              admin_password=None, network_info=None, block_device_info=None,
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

        if self.session.container_defined(instance.name, instance):
            raise exception.InstanceExists(name=instance.name)

        start = time.time()
        try:
            self.image.setup_image(context, instance, image_meta)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.exception(_LE('Upload image failed: %(e)s'),
                              {'e': ex})

        try:
            self.create_container(instance, injected_files, network_info,
                                  block_device_info, rescue, need_vif_plugged)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.exception(_LE('Container creation failed: %(e)s'),
                              {'e': ex})
        end = time.time()
        total = end - start
        LOG.debug('Creation took %s seconds to boot.' % total)

    def create_container(self, instance, injected_files, network_info,
                         block_device_info, rescue, need_vif_plugged):
        if not self.session.container_defined(instance.name, instance):
            container_config = (self.container_config.create_container(
                                instance, injected_files, block_device_info,
                                rescue))

            eventlet.spawn(self.session.container_init,
                           container_config, instance,
                           instance.host).wait()

            self.start_container(container_config, instance, network_info,
                                 need_vif_plugged)

    def start_container(self, container_config, instance, network_info,
                        need_vif_plugged):
        LOG.debug('Starting instance')

        if self.session.container_running(instance):
            return

        timeout = CONF.vif_plugging_timeout
        # check to see if neutron is ready before
        # doing anything else
        if (self.session.container_defined(instance.name, instance)
                and need_vif_plugged and utils.is_neutron() and timeout):
            events = self._get_neutron_events(network_info)
        else:
            events = []

        try:
            with self.virtapi.wait_for_instance_event(
                    instance, events, deadline=timeout,
                    error_callback=self._neutron_failed_callback):
                self.plug_vifs(
                    container_config, instance, network_info,
                    need_vif_plugged)
        except exception.VirtualInterfaceCreateException:
            LOG.info(_LW('Failed to connect networking to instance'))

        self.session.container_start(instance.name, instance)

    def reboot(self, context, instance, network_info, reboot_type,
               block_device_info=None, bad_volumes_callback=None):
        LOG.debug('container reboot')
        return self.session.container_reboot(instance)

    def plug_vifs(self, container_config, instance, network_info,
                  need_vif_plugged):
        for viface in network_info:
            container_config = self.container_config.configure_network_devices(
                container_config, instance, viface)
            if need_vif_plugged:
                self.vif_driver.plug(instance, viface)
        self._start_firewall(instance, network_info)

    def unplug_vifs(self, instance, network_info):
        self._unplug_vifs(instance, network_info, False)
        self._start_firewall(instance, network_info)

    def destroy(self, context, instance, network_info, block_device_info=None,
                destroy_disks=True, migrate_data=None):
        self.session.container_destroy(instance.name, instance.host,
                                       instance)
        self.cleanup(context, instance, network_info, block_device_info)

    def power_off(self, instance, timeout=0, retry_interval=0):
        return self.session.container_stop(instance.name,
                                           instance.host,
                                           instance)

    def power_on(self, context, instance, network_info,
                 block_device_info=None):
        return self.session.container_start(instance.name, instance)

    def pause(self, instance):
        return self.session.container_pause(instance.name, instance)

    def unpause(self, instance):
        return self.session.container_unpause(instance.name, instance)

    def suspend(self, context, instance):
        return self.session.container_pause(instance.name, instance)

    def resume(self, context, instance, network_info, block_device_info=None):
        return self.sessioncontainer_unpause(instance.name, instance)

    def rescue(self, context, instance, network_info, image_meta,
               rescue_password):
        LOG.debug('Container rescue')
        if not self.session.container_defined(instance.name, instance):
            msg = _('Unable to find instance')
            raise exception.NovaException(msg)

        self.session.container_stop(instance.name, instance.host)
        self._container_local_copy(instance)
        self.session.container_destroy(instance.name, instance.host,
                                       instance)

        self.spawn(context, instance, image_meta, injected_files=None,
                   admin_password=None, network_info=network_info,
                   block_device_info=None, need_vif_plugged=False,
                   rescue=True)

    def _container_local_copy(self, instance):
        container_snapshot = {
            'name': 'snap',
            'stateful': False
        }
        self.session.container_snapshot(container_snapshot, instance)

        ''' Creating container copy '''
        container_copy = {
            "config": None,
            "name": "%s-backup" % instance.name,
            "profiles": None,
            "source": {
                "source": "%s/snap" % instance.name,
                "type": "copy"}}
        self.session.container_copy(container_copy, instance)

    def unrescue(self, instance, network_info):
        LOG.debug('Conainer unrescue')
        old_name = '%s-backup' % instance.name
        container_config = {
            'name': '%s' % instance.name
        }

        self.session.container_move(old_name, container_config,
                                    instance)
        self.session.container_destroy(instance.name,
                                       instance.host,
                                       instance)

    def _unplug_vifs(self, instance, network_info, ignore_errors):
        """Unplug VIFs from networks."""
        for viface in network_info:
            try:
                self.vif_driver.unplug(instance, viface)
            except exception.NovaException:
                if not ignore_errors:
                    raise

    def cleanup(self, context, instance, network_info, block_device_info=None,
                destroy_disks=True, migrate_data=None, destroy_vifs=True):
        if destroy_vifs:
            self._unplug_vifs(instance, network_info, True)

        LOG.debug('container cleanup')
        container_dir = self.container_dir.get_instance_dir(instance.name)
        if os.path.exists(container_dir):
            shutil.rmtree(container_dir)

    def get_info(self, instance):
        container_state = self.session.container_state(instance)
        return hardware.InstanceInfo(state=container_state,
                                     max_mem_kb=0,
                                     mem_kb=0,
                                     num_cpu=2,
                                     cpu_time_ns=0)

    def get_console_output(self, context, instance):
        LOG.debug('in console output')

        console_log = self.container_dir.get_console_path(instance.name)
        if not os.path.exists(console_log):
            return
        uid = pwd.getpwuid(os.getuid()).pw_uid
        utils.execute('chown', '%s:%s' % (uid, uid),
                      console_log, run_as_root=True)
        utils.execute('chmod', '755',
                      os.path.join(
                          self.container_dir.get_container_dir(
                              instance.name), instance.name),
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
            self.session.container_update(container_config, instance)
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
                  {'event': event_name, 'uuid': instance.name})
        if CONF.vif_plugging_is_fatal:
            raise exception.VirtualInterfaceCreateException()

    def _start_firewall(self, instance, network_info):
        self.firewall_driver.setup_basic_filtering(instance, network_info)
        self.firewall_driver.prepare_instance_filter(instance, network_info)
        self.firewall_driver.apply_instance_filter(instance, network_info)

    def _stop_firewall(self, instance, network_info):
        self.firewall_driver.unfilter_instance(instance, network_info)
