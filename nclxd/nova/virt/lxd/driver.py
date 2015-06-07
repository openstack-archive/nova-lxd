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

"""
LXD Driver
"""

import socket

from oslo_config import cfg
from oslo_log import log as logging

from pylxd import api

from nova import exception
from nova.i18n import _, _LE
from nova.virt import driver
from nova.virt import event as virtevent
from nova.virt import hardware

import container
import host
import migration

lxd_opts = [
    cfg.StrOpt('lxd_root_dir',
               default='/var/lib/lxd/',
               help='Default LXD directory'),
    cfg.StrOpt('lxd_image_type',
               default='nova.virt.lxd.image.DefaultContainerImage',
               help='Default image')
]

CONF = cfg.CONF
CONF.register_opts(lxd_opts, 'lxd')
LOG = logging.getLogger(__name__)


class LXDDriver(driver.ComputeDriver):

    capabilities = {
        "has_imagecache": False,
        "supports_recreate": False,
        "supports_migrate_to_same_host": False
    }

    def __init__(self, virtapi):
        self.virtapi = virtapi

        self.lxd = api.API()

        self.container = container.Container(self.lxd, self.virtapi)
        self.migration = migration.Migration()
        self.host = host.Host(self.lxd)

    def init_host(self, host):
        try:
            self.lxd.host_ping()
        except Exception as ex:
            LOG.exception(_LE('Unable to connect to LXD daemon: %s') % ex)
            raise

    def get_info(self, instance):
        istate = self.container.container_state(instance)
        return hardware.InstanceInfo(state=istate,
                                     max_mem_kb=0,
                                     mem_kb=0,
                                     num_cpu=1,
                                     cpu_time_ns=0)

    def instance_exists(self, instance):
        try:
            return instance.uuid in self.list_instance_uuids()
        except NotImplementedError:
            return instance.name in self.list_instances()

    def list_instances(self):
        return self.lxd.container_list()

    def list_instance_uuids(self):
        return self.lxd.container_list()

    def plug_vifs(self, instance, network_info):
        for vif in network_info:
            self.container.plug_vifs(instance, network_info)

    def unplug_vifs(self, instance, network_info, ignore_errors):
        try:
            for vif in network_info:
                self.container.unplug_vifs(instance, network_info)
        except exception.Exception:
            if not ignore_errors:
                raise

    def rebuild(self, context, instance, image_meta, injected_files,
                admin_password, bdms, detach_block_devices,
                attach_block_devices, network_info=None,
                recreate=False, block_device_info=None,
                preserve_ephemeral=False):
        return self.container.container_rebuild(context, instance, image_meta,
                injected_files, admin_password, bdms, detach_block_devices,
                attach_block_devices, network_info=None,
                recreate=False, block_device_info=None,
                preserve_ephemeral=False)

    def spawn(self, context, instance, image_meta, injected_files,
              admin_password, network_info=None, block_device_info=None):
        return self.container.container_start(context, instance, image_meta,
                                              injected_files, admin_password,
                                              network_info, block_device_info)

    def destroy(self, context, instance, network_info, block_device_info=None,
                destroy_disks=True, migrate_data=None):
        return self.container.container_destroy(context, instance,
                                                network_info,
                                                block_device_info,
                                                destroy_disks,
                                                migrate_data)

    def cleanup(self, context, instance, network_info, block_device_info=None,
                destroy_disks=True, migrate_data=None, destroy_vifs=True):
        return self.container.container_cleanup(context, instance,
                                         network_info, block_device_info,
                                         destroy_disks, migrate_data,
                                         destroy_vifs)

    def reboot(self, context, instance, network_info, reboot_type,
               block_device_info=None, bad_volumes_callback=None):
        return self.container.container_reboot(context, instance,
                                               network_info,
                                               reboot_type, block_device_info,
                                               bad_volumes_callback)

    def get_console_pool_info(self, console_type):
        raise NotImplementedError()

    def get_console_output(self, context, instance):
        return self.container.get_console_output(context, instance)

    def get_vnc_console(self, context, instance):
        raise NotImplementedError()

    def get_spice_console(self, context, instance):
        raise NotImplementedError()

    def get_rdp_console(self, context, instance):
        raise NotImplementedError()

    def get_serial_console(self, context, instance):
        raise NotImplementedError()

    def get_diagnostics(self, instance):
        raise NotImplementedError()

    def get_instance_diagnostics(self, instance):
        raise NotImplementedError()

    def get_all_bw_counters(self, instances):
        raise NotImplementedError()

    def get_all_volume_usage(self, context, compute_host_bdms):
        raise NotImplementedError()

    def get_host_ip_addr(self):
        return self.host.get_host_ip_addr()

    def attach_volume(self, context, connection_info, instance, mountpoint,
                      disk_bus=None, device_type=None, encryption=None):
        return self.volume.container_attach(context, connection_info,
                                            instance, mountpoint,
                                            disk_bus, device_type,
                                            encryption)

    def detach_volume(self, connection_info, instance, mountpoint,
                      encryption=None):
        return self.volume.container_detach_volume(connection_info, instance,
                                                   mountpoint, encryption)

    def attach_interface(self, instance, image_meta, vif):
        return self.container.container_attach_interface(instance, image_meta,
                                                         vif)

    def detach_interface(self, instance, vif):
        return self.container.containre_detach_interface(instance, vif)

    def migrate_disk_and_power_off(self, context, instance, dest,
                                   flavor, network_info,
                                   block_device_info=None,
                                   timeout=0, retry_interval=0):
        raise NotImplementedError()

    def snapshot(self, context, instance, image_id, update_task_state):
        return self.container.snapshot(context, instance, image_id,
                                       update_task_state)

    def post_interrupted_snapshot_cleanup(self, context, instance):
        pass

    def finish_migration(self, context, migration, instance, disk_info,
                         network_info, image_meta, resize_instance,
                         block_device_info=None, power_on=True):
        raise NotImplementedError()

    def confirm_migration(self, migration, instance, network_info):
        raise NotImplementedError()

    def finish_revert_migration(self, context, instance, network_info,
                                block_device_info=None, power_on=True):
        raise NotImplementedError()

    def pause(self, instance):
        return self.container.container_pause(instance)

    def unpause(self, instance):
        return self.container.container_unpause(instance)

    def suspend(self, context, instance):
        return self.container.container_suspend(context, instance)

    def resume(self, context, instance, network_info, block_device_info=None):
        return self.container.container_resume(context, instance,
                                               network_info,
                                               block_device_info)

    def rescue(self, context, instance, network_info, image_meta,
               rescue_password):
        return self.container.container_rescue(context, instance,
                                               network_info, image_meta,
                                               rescue_password)

    def unrescue(self, instance, network_info):
        return self.container.container_unrescue(instance, network_info)

    def power_off(self, instance, timeout=0, retry_interval=0):
        return self.container.container_power_off(instance, timeout,
                                                  retry_interval)

    def power_on(self, context, instance, network_info,
                 block_device_info=None):
        return self.container.container_power_on(context, instance,
                                                 network_info,
                                                 block_device_info)

    def soft_delete(self, instance):
        return self.container.container_soft_deelte(instance)

    def restore(self, instance):
        return self.container.container_restore(instance)

    def get_available_resource(self, nodename):
        return self.host.get_available_resource(nodename)

    def pre_live_migration(self, context, instance, block_device_info,
                           network_info, disk_info, migrate_data=None):
        raise NotImplementedError()

    def live_migration(self, context, instance, dest,
                       post_method, recover_method, block_migration=False,
                       migrate_data=None):
        raise NotImplementedError()

    def rollback_live_migration_at_destination(self, context, instance,
                                               network_info,
                                               block_device_info,
                                               destroy_disks=True,
                                               migrate_data=None):
        raise NotImplementedError()

    def post_live_migration(self, context, instance, block_device_info,
                            migrate_data=None):
        pass

    def post_live_migration_at_source(self, context, instance, network_info):
        raise NotImplementedError(_("Hypervisor driver does not support "
                                    "post_live_migration_at_source method"))

    def post_live_migration_at_destination(self, context, instance,
                                           network_info,
                                           block_migration=False,
                                           block_device_info=None):
        raise NotImplementedError()

    def check_instance_shared_storage_local(self, context, instance):
        raise NotImplementedError()

    def check_instance_shared_storage_remote(self, context, data):
        raise NotImplementedError()

    def check_instance_shared_storage_cleanup(self, context, data):
        pass

    def check_can_live_migrate_destination(self, context, instance,
                                           src_compute_info, dst_compute_info,
                                           block_migration=False,
                                           disk_over_commit=False):
        raise NotImplementedError()

    def check_can_live_migrate_destination_cleanup(self, context,
                                                   dest_check_data):
        raise NotImplementedError()

    def check_can_live_migrate_source(self, context, instance,
                                      dest_check_data,
                                      block_device_info=None):
        raise NotImplementedError()

    def refresh_security_group_rules(self, security_group_id):
        raise NotImplementedError()

    def refresh_security_group_members(self, security_group_id):
        raise NotImplementedError()

    def refresh_provider_fw_rules(self):
        raise NotImplementedError()

    def refresh_instance_security_rules(self, instance):
        raise NotImplementedError()

    def ensure_filtering_rules_for_instance(self, instance, network_info):
        raise NotImplementedError()

    def filter_defer_apply_on(self):
        pass

    def filter_defer_apply_off(self):
        pass

    def unfilter_instance(self, instance, network_info):
        raise NotImplementedError()

    def inject_file(self, instance, b64_path, b64_contents):
        raise NotImplementedError()

    def inject_network_info(self, instance, nw_info):
        pass

    def poll_rebooting_instances(self, timeout, instances):
        raise NotImplementedError()

    def host_power_action(self, action):
        raise NotImplementedError()

    def host_maintenance_mode(self, host, mode):
        raise NotImplementedError()

    def set_host_enabled(self, enabled):
        raise NotImplementedError()

    def get_host_uptime(self):
        return self.host.get_host_uptime()

    def get_host_cpu_stats(self):
        return self.host.get_host_cpu_stats()

    def block_stats(self, instance, disk_id):
        return [0, 0, 0, 0, None]  # zulcss - fixme

    def deallocate_networks_on_reschedule(self, instance):
        return False

    def manage_image_cache(self, context, all_instances):
        pass

    def get_volume_connector(self, instance):
        raise NotImplementedError()

    def get_available_nodes(self, refresh=False):
        hostname = socket.gethostname()
        return [hostname]

    def node_is_available(self, nodename):
        if nodename in self.get_available_nodes():
            return True
        # Refresh and check again.
        return nodename in self.get_available_nodes(refresh=True)

    def get_per_instance_usage(self):
        return {}

    def instance_on_disk(self, instance):
        return False

    def register_event_listener(self, callback):
        self._compute_event_callback = callback

    def emit_event(self, event):
        if not self._compute_event_callback:
            LOG.debug("Discarding event %s", str(event))
            return

        if not isinstance(event, virtevent.Event):
            raise ValueError(
                _("Event must be an instance of nova.virt.event.Event"))

        try:
            LOG.debug("Emitting event %s", str(event))
            self._compute_event_callback(event)
        except Exception as ex:
            LOG.error(_LE("Exception dispatching event %(event)s: %(ex)s"),
                      {'event': event, 'ex': ex})

    def delete_instance_files(self, instance):
        return True

    @property
    def need_legacy_block_device_info(self):
        return True

    def volume_snapshot_create(self, context, instance, volume_id,
                               create_info):
        raise NotImplementedError()

    def volume_snapshot_delete(self, context, instance, volume_id,
                               snapshot_id, delete_info):
        raise NotImplementedError()

    def quiesce(self, context, instance, image_meta):
        return self.container.container_quiesce(context, instance, image_meta)

    def unquiesce(self, context, instance, image_meta):
        return self.container.container_unquiesce(context, instance,
                                                  image_meta)
