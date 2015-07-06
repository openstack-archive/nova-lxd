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

import socket

from nova import i18n
from nova.virt import driver
from oslo_config import cfg
from oslo_log import log as logging

import container_ops
import container_snapshot
import host

_ = i18n._

lxd_opts = [
    cfg.StrOpt('lxd_root_dir',
               default='/var/lib/lxd/',
               help='Default LXD directory'),
    cfg.IntOpt('lxd_timeout',
               default=5,
               help='Default LXD timeout'),
    cfg.StrOpt('lxd_default_profile',
               default='nclxd-profile',
               help='Default LXD profile')
]

CONF = cfg.CONF
CONF.register_opts(lxd_opts, 'lxd')
LOG = logging.getLogger(__name__)


class LXDDriver(driver.ComputeDriver):
    """LXD Lightervisor."""

    capabilities = {
        "has_imagecache": False,
        "supports_recreate": False,
        "supports_migrate_to_same_host": False
    }

    def __init__(self, virtapi):
        self.virtapi = virtapi

        self.container_ops = container_ops.LXDContainerOperations(virtapi)
        self.container_snapshot = container_snapshot.LXDSnapshot()
        self.host = host.LXDHost()

    def init_host(self, host):
        return self.container_ops.init_host(host)

    def get_info(self, instance):
        return self.container_ops.get_info(instance)

    def instance_exists(self, instance):
        try:
            return instance.uuid in self.list_instance_uuids()
        except NotImplementedError:
            return instance.name in self.list_instances()

    def estimate_instance_overhead(self, instance_info):
        return {'memory_mb': 0}

    def list_instances(self):
        return self.container_ops.list_instances()

    def list_instance_uuids(self):
        return self.container_ops.list_instances()

    def spawn(self, context, instance, image_meta, injected_files,
              admin_password, network_info=None, block_device_info=None):
        return self.container_ops.spawn(context, instance, image_meta,
                                        injected_files, admin_password,
                                        network_info, block_device_info)

    def destroy(self, context, instance, network_info, block_device_info=None,
                destroy_disks=True, migrate_data=None):
        return self.container_ops.destroy(context, instance, network_info,
                                          block_device_info, destroy_disks,
                                          migrate_data)
        self.cleanup(context, instance, network_info, block_device_info)

    def cleanup(self, context, instance, network_info, block_device_info=None,
                destroy_disks=True, migrate_data=None, destroy_vifs=True):
        return self.container_ops.cleanup(context, instance, network_info,
                                          block_device_info, destroy_disks,
                                          migrate_data, destroy_vifs)

    def reboot(self, context, instance, network_info, reboot_type,
               block_device_info=None, bad_volumes_callback=None):
        return self.container_ops.reboot(context, instance, network_info,
                                         reboot_type, block_device_info,
                                         bad_volumes_callback)

    def get_console_output(self, context, instance):
        return self.container_ops.get_console_output(context, instance)

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
        raise NotImplemented()

    def detach_volume(self, connection_info, instance, mountpoint,
                      encryption=None):
        raise NotImplemented()

    def attach_interface(self, instance, image_meta, vif):
        raise NotImplementedError()

    def detach_interface(self, instance, vif):
        raise NotImplementedError()

    def migrate_disk_and_power_off(self, context, instance, dest,
                                   flavor, network_info,
                                   block_device_info=None,
                                   timeout=0, retry_interval=0):
        raise NotImplementedError()

    def snapshot(self, context, instance, image_id, update_task_state):
        return self.container_snapshot.snapshot(context, instance, image_id,
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
        return self.container_ops.pause(instance)

    def unpause(self, instance):
        raise NotImplementedError()

    def suspend(self, context, instance):
        raise NotImplementedError()

    def resume(self, context, instance, network_info, block_device_info=None):
        raise NotImplementedError()

    def rescue(self, context, instance, network_info, image_meta,
               rescue_password):
        return self.container_ops.rescue(context, instance, network_info,
                                         image_meta, rescue_password)

    def unrescue(self, instance, network_info):
        return self.container_ops.unrescue(instance, network_info)

    def power_off(self, instance, timeout=0, retry_interval=0):
        return self.container_ops.power_off(instance, timeout=0,
                                            retry_interval=0)

    def power_on(self, context, instance, network_info,
                 block_device_info=None):
        return self.container_ops.power_on(context, instance, network_info,
                                           block_device_info)

    def soft_delete(self, instance):
        raise NotImplementedError()

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
                                      dest_check_data, block_device_info=None):
        raise NotImplementedError()

    def get_instance_disk_info(self, instance,
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

    def reset_network(self, instance):
        pass

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
        raise NotImplementedError()

    def block_stats(self, instance, disk_id):
        raise NotImplementedError()

    def deallocate_networks_on_reschedule(self, instance):
        """Does the driver want networks deallocated on reschedule?"""
        return False

    def macs_for_instance(self, instance):
        return None

    def manage_image_cache(self, context, all_instances):
        pass

    def add_to_aggregate(self, context, aggregate, host, **kwargs):
        raise NotImplementedError()

    def remove_from_aggregate(self, context, aggregate, host, **kwargs):
        raise NotImplementedError()

    def undo_aggregate_operation(self, context, op, aggregate,
                                 host, set_error=True):
        raise NotImplementedError()

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

    def volume_snapshot_create(self, context, instance, volume_id,
                               create_info):
        raise NotImplementedError()

    def volume_snapshot_delete(self, context, instance, volume_id,
                               snapshot_id, delete_info):
        raise NotImplementedError()

    def quiesce(self, context, instance, image_meta):
        raise NotImplementedError()

    def unquiesce(self, context, instance, image_meta):
        raise NotImplementedError()
