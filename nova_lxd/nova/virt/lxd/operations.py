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


from nova.api.metadata import base as instance_metadata
from nova.virt import configdrive
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

from nova_lxd.nova.virt.lxd import config as container_config
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
              rescue=False):
        """Start the LXD container

        Once this successfully completes, the instance should be
        running (power_state.RUNNING).

        If this fails, any partial instance should be completely
        cleaned up, and the virtualization platform should be in the state
        that it was before this call began.

        :param context: security context
        :param instance: nova.objects.instance.Instance
                         This function should use the data there to guide
                         the creation of the new instance.
        :param image_meta: image object returned by nova.image.glance that
                           defines the image from which to boot this instance
        :param injected_files: User files to inject into instance.
        :param admin_password: Administrator password to set in instance.
        :param network_info:
            :py:meth:`~nova.network.manager.NetworkManager.get_instance_nw_info`
        :param block_device_info: Information about block devices to be
                                  attached to the instance
        """
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

        try:
            # Step 1 - Fetch the image from glance
            self._fetch_image(context, instance, image_meta)

            # Step 2 - Setup the container network
            self._setup_network(instance, network_info)

            # Step 3 - Create the container profile
            self._setup_profile(instance_name, instance, network_info, rescue)

            # Step 4 - Create a config drive (optional)
            self._add_configdrive(instance, injected_files)

            # Step 5 - Configure and start the container
            self._setup_container(instance_name, instance, rescue)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Faild to start container '
                              '%(instance)s: %(ex)s'),
                          {'instance': instance.name, 'ex': ex},
                          instance=instance)
                self.destroy(context, instance, nework_info)

    def _fetch_image(self, context, instance, image_meta):
        """Fetch the LXD image from glance

        :param context: nova security context
        :param instance: nova instance object
        :param image_meta: nova image opbject
        """
        LOG.debug('_fetch_image called for instance', instance=instance)
        try:
            # Download the image from glance and upload the image
            # to the local LXD image store.
            self.image.setup_image(context, instance, image_meta)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Upload image failed for %(instance)s '
                              'for %(image)s: %(e)s'),
                              {'instance': instance.name,
                               'image': instance.image_ref,
                               'ex': ex}, instance=instance)

    def _setup_network(self, instance_name, instance, network_info):
        """Setup the network when creating the lXD container

        :param instance_name: nova instance name
        :param instance: nova instance object
        :param network_info: instance network configuration
        """
        LOG.debug('_setup_netwokr called for instance', instance=instance)
        try:
            self.plug_vifs(instance, network_info):
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Failed to create container network for '
                              '%(instance)s: %(ex)s'),
                              {'instance': instance_name, 'ex': ex},
                              instance=instance)

    def _setup_profile(self, instance_name, instance, network_info, rescue):
        """Create an LXD container profile for the nova intsance

        :param instance_name: nova instance name
        :param instance: nova instance object
        :param newtwork_info: nova instance netowkr configuration
        :param rescue: boolean rescue instance if True needed to create
        """
        LOG.debug('_setup_profile called for instance', instance=instance)
        try:
            # Setup the container profile based on the nova
            # instance object and network objects
            self.container_config.create_profile(instance, network_info,
                                                 rescue)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Failed to create a profile for'
                              ' %(instance)s: %(ex)s'),
                              {'instance': instance_name,
                               'ex': ex}, instance=instance)

    def _setup_container(self, instance_name, instance, rescue):
        """Create and start the LXD container.

        :param instance_name: nova instjace name
        :param instance: nova instance object
        :param rescue: boolean rescue container
        """
        LOG.debug('_setup_container called for instance', instance=instance)
        try:
            # Create the container
            container_config = \
                self.container_config.create_container(instance, rescue)
            self.session.container_init(container_config, instance, rescue)

            # Start the container
            self.session.container_start(instance_name, instance)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.exception(_LE('Container creation failed for '
                                  '%(insance)s: %(ex)s'),
                                  {'instance': instance.name,
                                   'ex': ex}, instance=instance)

    def _add_configdirve(self, instance, injected_files):
        """Confiugre the config drive for the container

        :param instance: nova instance object
        :param injected_files: instance injected files
        """
        LOG.debug('add_configdrive called for instance', instance=instance)

        extra_md = {}
        inst_md = instance_metadata.InstanceMetadata(instance,
                    content=injected_files,
                    extra_md=extra_md)
        name = instance.name
        try:
            with configdrive.ConfigDriveBuilder(instance_md=inst_md) as cdb:
                contianer_configdrive = (
                    self.container_dir.get_container_configdrive(name)
                )
                cdb.make_drive(container_configdrive)
        except Exception as e:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Creating config drive failed with error: %s'),
                    e, instance=instance)

    def reboot(self, context, instance, network_info, reboot_type,
               block_device_info=None, bad_volumes_callback=None):
        LOG.debug('container reboot')
        return self.session.container_reboot(instance)

    def plug_vifs(self, instance, network_info):
        """Setup the container network on the host

         :param instance: nova instance object
         :param network_info: instnace network configuration
         """
        LOG.debug('plug_vifs called for instance', instance=instance)
        try:
            for viface in network_info:
                    self.vif_driver.plug(instance, viface)
            self._start_firewall(instance, network_info)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Failed to configure container network'
                              ' for %(instnace)s: %(ex)s'),
                              {'instance': instance.name, 'ex': ex},
                              instance=instance)

    def unplug_vifs(self, instance, network_info):
        """Unconfigure the LXD container network

           :param instance: nova intance object
           :param network_info: instance network confiugration
        """
        try:
            self._unplug_vifs(instance, network_info, False)
            self._start_firewall(instance, network_info)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Failed to remove container network'
                              ' for %(instnace)s: %(ex)s'),
                             {'instance': instance.name, 'ex': ex},
                              instance=instance)


    def destroy(self, context, instance, network_info, block_device_info=None,
                destroy_disks=True, migrate_data=None):
        self.session.profile_delete(instance)
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
                   block_device_info=None,
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
