# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# Copyright (c) 2010 Citrix Systems, Inc.
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

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import units

from nova.i18n import _, _LE, _LI, _LW
from nova.compute import power_state
from nova import exception
from nova import utils

import image
import profile
import vif

import container_utils


CONF = cfg.CONF
CONF.import_opt('vif_plugging_timeout', 'nova.virt.driver')
CONF.import_opt('vif_plugging_is_fatal', 'nova.virt.driver')

LOG = logging.getLogger(__name__)

MAX_CONSOLE_BYTES = 100 * units.Ki

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
    'UNKNOWN': power_state.NOSTATE
}


class Container(object):
    def __init__(self, lxd, virtapi):
        self.lxd = lxd
        self.virtapi = virtapi

        self.image_driver = image.load_driver(CONF.lxd.lxd_image_type,
                                              self.lxd)
        self.profile = profile.LXDProfile(self.lxd)
        self.vif_driver = vif.LXDGenericDriver()

    def container_rebuild(self, context, instance, image_meta, injected_files,
                admin_password, bdms, detach_block_devices,
                attach_block_devices, network_info, recreate,
                block_device_info,
                preserve_ephemeral):
        raise NotImplemented()

    def container_start(self, context, instance, image_meta, injected_files,
              admin_password, network_info, block_device_info):
        try:
            LOG.info(_LI('Starting container'), instance=instance)
            if self.lxd.container_defined(instance.uuid):
                raise exception.InstanceExists(name=instance.uuid)

            self.image_driver.setup_container(context, instance, image_meta)
            self.profile.profile_create(instance, network_info)
            self._setup_container(instance)
            self._start_container(instance, network_info)
        except Exception:
            with excutils.save_and_reraise_exception():
                self.container_destroy(context, instance, network_info,
                                       block_device_info, destroy_disks=None,
                                       migrate_data=None)

    def container_destroy(self, context, instance, network_info,
                block_device_info, destroy_disks, migrate_data):
        LOG.info(_LI('Destroying container'))
        try:
            if not self.lxd.container_defined(instance.uuid):
                return

            self.lxd.container_destroy(instance.uuid)
            self.container_cleanup(context, instance, network_info,
                               block_device_info, destroy_disks=None,
                               migrate_data=None)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.exception(_LE('Unable to destroy instance: %s ') % ex)

    def container_reboot(self, context, instance, network_info, reboot_type,
               block_device_info=None, bad_volumes_callback=None):

        try:
            if not self.lxd.container_defined(instance.uuid):
                msg = _('Container does not exist')
                raise exception.NovaException(msg)

            return self.lxd.container_reboot(instance.uuid, 20)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.exception(_LE('Unable to destroy instance: %s ') % ex)

    def get_console_output(self, context, instance):
        try:
            if not self.lxd.container_defined(instance.uuid):
                msg = _('Container does not exist')
                raise exception.NovaException(msg)

            console_log = container_utils.get_console_path(instance)
            uid = pwd.getpwuid(os.getuid()).pw_uid
            utils.execute('chown', '%s:%s' % (uid, uid),
                          console_log, run_as_root=True)
            utils.execute('chmod', '755',
                          container_utils.get_container_dir(instance),
                          run_as_root=True)
            with open(console_log , 'rb') as fp:
                log_data, remaning = utils.last_bytes(fp,
                                                       MAX_CONSOLE_BYTES)
                return log_data


        except Exception as ex:
            LOG.exception(_LE('Failed container: %s') % ex)
            return ""

    def container_cleanup(self, context, instance, network_info,
                block_device_info, destroy_disks, migrate_data,
                destroy_vifs=True):
        LOG.info(_LI('Cleaning up container'))
        try:
            self.profile.profile_delete(instance)
            self.unplug_vifs(instance, network_info)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.excpetion(_LE('Unable to clean up instance: %s') % ex)

    def container_state(self, instance):
        try:
            container_state = self.lxd.container_state(instance.uuid)
            state = LXD_POWER_STATES[container_state]
        except Exception:
            state = power_state.NOSTATE
        return state

    def container_pause(self, instance):

        raise NotImplementedError()

    def container_unpause(self, instance):
        raise NotImplementedError()

    def container_suspend(self, context, instance):
        try:
            if not self.lxd.container_defined(instance.uuid):
                msg = _("Container is not defined")
                raise exception.NovaException(msg)

            self.lxd.container_suspend(instance.uuid, 20)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.exception(_LE("Unable to suspend container"))

    def container_resume(self, context, instance, network_info,
                         block_device_info=None):
        try:
            if not self.lxd.container_defined(instance.uuid):
                msg = _('Container does not exist.')
                raise exception.NovaException(msg)

            self.lxd.container_resume(instance.uuid, 20)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.exception(_LE("Unable to resume container"))

    def container_rescue(self, context, instance, network_info, image_meta,
               rescue_password):
        raise NotImplementedError()

    def container_unrescue(self, instance, network_info):
        raise NotImplementedError()

    def container_power_off(self, instance, timeout=0, retry_interval=0):
        try:
            if not self.lxd.container_defined(instance.uuid):
                msg = _('Container is not defined')
                raise exception.NovaException(msg)

            self.lxd.container_stop(instance.uuid, 20)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.execption(_LE("Unable to power off container"))

        raise NotImplementedError()

    def container_power_on(self, context, instance, network_info,
                 block_device_info):
        try:
            if not self.lxd.container_defined(instance.uuid):
                msg = _('Container is not defined')
                raise exception.NovaException(msg)

            self.lxd.container_start(instance.uuid, 20)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.exception(_LE("Unable to power on conatainer"))

    def container_soft_delete(self, instance):
        raise NotImplementedError()

    def container_restore(self, instance):
        raise NotImplementedError()

    def container_get_resource(self, nodename):
        raise NotImplementedError()

    def container_inject_file(self, instance, b64_path, b64_contents):
        raise NotImplementedError()

    def container_inject_network_info(self, instance, nw_info):
        pass

    def container_poll_rebooting_instances(self, timeout, instances):
        raise NotImplementedError()

    def container_attach_interface(self, instance, image_meta, vif):
        raise NotImplementedError()

    def container_detach_interface(self, instance, vif):
        raise NotImplementedError()

    def container_snapshot(self, context, instance, image_id,
                           update_task_state):
        raise NotImplementedError()

    def post_interrupted_snapshot_cleanup(self, context, instance):
        pass

    def container_quiesce(self, context, instance, image_meta):
        raise NotImplementedError()

    def container_unquiesce(self, context, instance, image_meta):
        raise NotImplementedError()

    def _setup_container(self, instance):
        LOG.debug('Setting up container')

        if not os.path.exists(
                container_utils.get_container_image(instance)):
            msg = _('Container image doesnt exist.')
            raise exception.NovaException(msg)

        if instance.uuid:
            container = {}
            container['name'] = instance.uuid
            container['profiles'] = ['%s' % instance.uuid]
            container['source'] = {
                'type': 'image',
                'alias': instance.image_ref
            }
            (state, data) = self.lxd.container_init(container)
            self._wait_for_container(data.get('operation').split('/')[3])

    def _start_container(self, instance, network_info):
        timeout = CONF.vif_plugging_timeout
        # check to see if neutron is ready before
        # doing anything else
        if (not self.lxd.container_running(instance.uuid) and
                utils.is_neutron() and timeout):
            events = self._get_neutron_events(network_info)
        else:
            events = {}

        try:
            with self.virtapi.wait_for_instance_event(
                    instance, events, deadline=timeout,
                    error_callback=self._neutron_failed_callback):
                self.plug_vifs(instance, network_info)
        except exception.VirtualInterfaceCreateException:
            LOG.info(_LW('Failed to connect networking to instance'))

        (state, data) = self.lxd.container_start(instance.uuid, 20)
        self._wait_for_container(data.get('operation').split('/')[3])

    def _destroy_container(self, context, instance, network_info,
                           block_device_info,
                destroy_disks, migrate_data):
        if self.lxd.container_defined(instance.uuid):
            msg = _('Unable to find container')
            raise exception.NovaException(msg)

        self.lxd.container_destroy(instance.uuid)

    def plug_vifs(self, instance, network_info):
        for _vif in network_info:
            self.vif_driver.plug(instance, _vif)

    def unplug_vifs(self, instance, network_info):
        for _vif in network_info:
            self.vif_driver.unplug(instance, _vif)

    def _wait_for_container(self, oid):
        if not oid:
            msg = _('Unable to determine container operation')
            raise exception.NovaException(msg)

        if not self.lxd.wait_container_operation(oid, 200, 20):
            msg = _('Container creation timed out')
            raise exception.NovaException(msg)

    def _get_neutron_events(self, network_info):
        return [('network-vif-plugged', vif['id'])
                for vif in network_info if vif.get('active', True) is False]

    def _neutron_failed_callback(self, event_name, instance):
        LOG.error(_LE('Neutron Reported failure on event '
                      '%(event)s for instance %(uuid)s'),
                  {'event': event_name, 'uuid': instance.uuid})
        if CONF.vif_plugging_is_fatal:
            raise exception.VirtualInterfaceCreateException()
