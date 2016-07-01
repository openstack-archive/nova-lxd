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

from __future__ import absolute_import

import os
import platform
import socket

from nova import exception
from nova import i18n
from nova.virt import driver
from oslo_config import cfg
from oslo_log import log as logging
import pylxd
from pylxd import exceptions as lxd_exceptions
from nova.compute import utils as compute_utils

from nova.virt.lxd import container_snapshot
from nova.virt.lxd import migrate
from nova.virt.lxd import operations as container_ops
from nova.virt.lxd import vif as lxd_vif

from nova.compute import arch
from nova.compute import hv_type
from nova.compute import vm_mode
from oslo_utils import units
from oslo_serialization import jsonutils
from nova import utils
import psutil
from nova.virt import firewall

_ = i18n._
_LW = i18n._LW

lxd_opts = [
    cfg.StrOpt('root_dir',
               default='/var/lib/lxd/',
               help='Default LXD directory'),
    cfg.IntOpt('timeout',
               default=-1,
               help='Default LXD timeout'),
    cfg.IntOpt('retry_interval',
               default=2,
               help='How often to retry in seconds when a'
                    'request does conflict'),
    cfg.BoolOpt('allow_live_migrate',
                default=False,
                help='Determine wheter to allow live migration'),
]

CONF = cfg.CONF
CONF.register_opts(lxd_opts, 'lxd')
LOG = logging.getLogger(__name__)


class LXDDriver(driver.ComputeDriver):

    """LXD Lightervisor."""

    capabilities = {
        "has_imagecache": False,
        "supports_recreate": False,
        "supports_migrate_to_same_host": False,
        "supports_attach_interface": True
    }

    def __init__(self, virtapi):
        super(LXDDriver, self).__init__(virtapi)

        self.vif_driver = lxd_vif.LXDGenericDriver()

        self.container_ops = container_ops.LXDContainerOperations()
        self.container_snapshot = container_snapshot.LXDSnapshot()
        self.container_migrate = migrate.LXDContainerMigrate()

        # The pylxd client, initialized with init_host
        self.client = None

        self.firewall_driver = firewall.load_driver(
            default='nova.virt.firewall.NoopFirewallDriver')

    def init_host(self, host):
        try:
            self.client = pylxd.Client()
            return True
        except lxd_exceptions.ClientConnectionFailed as e:
            msg = _('Unable to connect to LXD daemon: %s') % e
            raise exception.HostNotFound(msg)

    def get_info(self, instance):
        return self.container_ops.get_info(instance)

    def instance_exists(self, instance):
        return instance.name in self.list_instances()

    def plug_vifs(self, instance, network_info):
        """Plug VIFs into networks."""
        for vif in network_info:
            self.vif_driver.plug(instance, vif)

    def unplug_vifs(self, instance, network_info):
        """Unplug VIFs from networks."""
        for vif in network_info:
            try:
                self.vif_driver.unplug(instance, vif)
            except exception.NovaException:
                pass

    def estimate_instance_overhead(self, instance_info):
        return {'memory_mb': 0}

    def list_instances(self):
        return self.container_ops.list_instances()

    def list_instance_uuids(self):
        raise NotImplementedError()

    def spawn(self, context, instance, image_meta, injected_files,
              admin_password, network_info=None, block_device_info=None):
        self.container_ops.spawn(context, instance, image_meta,
                                 injected_files, admin_password,
                                 network_info, block_device_info)

    def destroy(self, context, instance, network_info, block_device_info=None,
                destroy_disks=True, migrate_data=None):
        self.container_ops.destroy(context, instance, network_info,
                                   block_device_info, destroy_disks,
                                   migrate_data)

    def cleanup(self, context, instance, network_info, block_device_info=None,
                destroy_disks=True, migrate_data=None, destroy_vifs=True):
        self.container_ops.cleanup(context, instance, network_info,
                                   block_device_info, destroy_disks,
                                   migrate_data, destroy_vifs)

    def reboot(self, context, instance, network_info, reboot_type,
               block_device_info=None, bad_volumes_callback=None):
        self.container_ops.reboot(context, instance, network_info,
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
        ips = compute_utils.get_machine_ips()
        if CONF.my_ip not in ips:
            LOG.warn(_LW('my_ip address (%(my_ip)s) was not found on '
                         'any of the interfaces: %(ifaces)s'),
                     {'my_ip': CONF.my_ip, 'ifaces': ", ".join(ips)})
        return CONF.my_ip

    def attach_volume(self, context, connection_info, instance, mountpoint,
                      disk_bus=None, device_type=None, encryption=None):
        raise NotImplementedError()

    def detach_volume(self, connection_info, instance, mountpoint,
                      encryption=None):
        raise NotImplementedError()

    def swap_volume(self, old_connection_info, new_connection_info,
                    instance, mountpoint, resize_to):
        raise NotImplementedError()

    def attach_interface(self, instance, image_meta, vif):
        return self.container_ops.container_attach_interface(instance,
                                                             image_meta,
                                                             vif)

    def detach_interface(self, instance, vif):
        return self.container_ops.container_detach_interface(instance, vif)

    def migrate_disk_and_power_off(self, context, instance, dest,
                                   flavor, network_info,
                                   block_device_info=None,
                                   timeout=0, retry_interval=0):
        return self.container_migrate.migrate_disk_and_power_off(
            context, instance, dest, flavor,
            network_info, block_device_info, timeout,
            retry_interval)

    def snapshot(self, context, instance, image_id, update_task_state):
        return self.container_snapshot.snapshot(context, instance, image_id,
                                                update_task_state)

    def post_interrupted_snapshot_cleanup(self, context, instance):
        pass

    def finish_migration(self, context, migration, instance, disk_info,
                         network_info, image_meta, resize_instance,
                         block_device_info=None, power_on=True):
        return self.container_migrate.finish_migration(
            context, migration, instance, disk_info,
            network_info, image_meta, resize_instance,
            block_device_info, power_on)

    def confirm_migration(self, migration, instance, network_info):
        return self.container_migrate.confirm_migration(migration,
                                                        instance,
                                                        network_info)

    def finish_revert_migration(self, context, instance, network_info,
                                block_device_info=None, power_on=True):
        return self.container_migrate.finish_revert_migration(
            context, instance, network_info, block_device_info,
            power_on)

    def pause(self, instance):
        self.container_ops.pause(instance)

    def unpause(self, instance):
        self.container_ops.unpause(instance)

    def suspend(self, context, instance):
        self.container_ops.suspend(context, instance)

    def resume(self, context, instance, network_info, block_device_info=None):
        self.container_ops.resume(context, instance, network_info,
                                  block_device_info)

    def rescue(self, context, instance, network_info, image_meta,
               rescue_password):
        self.container_ops.rescue(context, instance, network_info,
                                  image_meta, rescue_password)

    def unrescue(self, instance, network_info):
        return self.container_ops.unrescue(instance, network_info)

    def power_off(self, instance, timeout=0, retry_interval=0):
        self.container_ops.power_off(instance, timeout=0,
                                     retry_interval=0)

    def power_on(self, context, instance, network_info,
                 block_device_info=None):
        self.container_ops.power_on(context, instance, network_info,
                                    block_device_info)

    def soft_delete(self, instance):
        raise NotImplementedError()

    def get_available_resource(self, nodename):
        LOG.debug('In get_available_resource')

        local_cpu_info = self._get_cpuinfo()
        cpu_topology = local_cpu_info['topology']
        vcpus = (int(cpu_topology['cores']) *
                 int(cpu_topology['sockets']) *
                 int(cpu_topology['threads']))

        local_memory_info = self._get_memory_mb_usage()
        local_disk_info = self._get_fs_info(CONF.lxd.root_dir)

        data = {
            'vcpus': vcpus,
            'memory_mb': local_memory_info['total'] / units.Mi,
            'memory_mb_used': local_memory_info['used'] / units.Mi,
            'local_gb': local_disk_info['total'] / units.Gi,
            'local_gb_used': local_disk_info['used'] / units.Gi,
            'vcpus_used': 0,
            'hypervisor_type': 'lxd',
            'hypervisor_version': '011',
            'cpu_info': jsonutils.dumps(local_cpu_info),
            'hypervisor_hostname': socket.gethostname(),
            'supported_instances':
                [(arch.I686, hv_type.LXD, vm_mode.EXE),
                    (arch.X86_64, hv_type.LXD, vm_mode.EXE),
                    (arch.I686, hv_type.LXC, vm_mode.EXE),
                    (arch.X86_64, hv_type.LXC, vm_mode.EXE)],
            'numa_topology': None,
        }

        return data

    def pre_live_migration(self, context, instance, block_device_info,
                           network_info, disk_info, migrate_data=None):
        self.container_migrate.pre_live_migration(
            context, instance, block_device_info, network_info,
            disk_info, migrate_data)

    def live_migration(self, context, instance, dest,
                       post_method, recover_method, block_migration=False,
                       migrate_data=None):
        self.container_migrate.live_migration(
            context, instance, dest, post_method,
            recover_method, block_migration,
            migrate_data)

    def post_live_migration(self, context, instance, block_device_info,
                            migrate_data=None):
        self.container_migrate.post_live_migration(
            context, instance, block_device_info, migrate_data)

    def post_live_migration_at_destination(self, context, instance,
                                           network_info,
                                           block_migration=False,
                                           block_device_info=None):
        self.container_migrate.post_live_migration_at_destination(
            context, instance, network_info, block_migration,
            block_device_info)

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
        return self.container_migrate.check_can_live_migrate_destination(
            context, instance, src_compute_info, dst_compute_info,
            block_migration, disk_over_commit)

    def check_can_live_migrate_destination_cleanup(self, context,
                                                   dest_check_data):
        self.container_migrate.check_can_live_migrate_destination_cleanup(
            context, dest_check_data)

    def post_live_migration_at_source(self, context, instance, network_info):
        return self.container_migrate.post_live_migration_at_snurce(
            context, instance, network_info)

    def check_can_live_migrate_source(self, context, instance,
                                      dest_check_data, block_device_info=None):
        self.container_migrate.check_can_live_migrate_source(
            context, instance, dest_check_data,
            block_device_info
        )

    def get_instance_disk_info(self, instance,
                               block_device_info=None):
        raise NotImplementedError()

    def refresh_instance_security_rules(self, instance):
        return self.firewall_driver.refresh_instance_security_rules(
            instance)

    def ensure_filtering_rules_for_instance(self, instance, network_info):
        return self.firewall_driver.ensure_filtering_rules_for_instance(
            instance, network_info)

    def filter_defer_apply_on(self):
        return self.firewall_driver.filter_defer_apply_on()

    def filter_defer_apply_off(self):
        return self.firewall_driver.filter_defer_apply_off()

    def unfilter_instance(self, instance, network_info):
        return self.firewall_driver.unfilter_instance(
            instance, network_info)

    def poll_rebooting_instances(self, timeout, instances):
        raise NotImplementedError()

    def host_power_action(self, action):
        raise NotImplementedError()

    def host_maintenance_mode(self, host, mode):
        raise NotImplementedError()

    def set_host_enabled(self, enabled):
        raise NotImplementedError()

    def get_host_uptime(self):
        out, err = utils.execute('env', 'LANG=C', 'uptime')
        return out

    def get_host_cpu_stats(self):
        cpuinfo = self._get_cpu_info()
        return {
            'kernel': int(psutil.cpu_times()[2]),
            'idle': int(psutil.cpu_times()[3]),
            'user': int(psutil.cpu_times()[0]),
            'iowait': int(psutil.cpu_times()[4]),
            'frequency': cpuinfo.get('cpu mhz', 0)
        }

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
        return {'ip': CONF.my_block_storage_ip,
                'initiator': 'fake',
                'host': 'fakehost'}

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

    # Private methods

    def _get_fs_info(self, path):
        """Get free/used/total space info for a filesystem

        :param path: Any dirent on the filesystem
        :returns: A dict containing
              :free: How much space is free (in bytes)
              :used: How much space is used (in bytes)
              :total: How big the filesytem is (in bytes)
        """
        hddinfo = os.statvfs(path)
        total = hddinfo.f_blocks * hddinfo.f_bsize
        available = hddinfo.f_bavail * hddinfo.f_bsize
        used = total - available
        return {'total': total,
                'available': available,
                'used': used}

    def _get_memory_mb_usage(self):
        """Get the used memory size(MB) of the host.

        :returns: the total usage of memory(MB)
        """

        with open('/proc/meminfo') as fp:
            m = fp.read().split()
            idx1 = m.index('MemTotal:')
            idx2 = m.index('MemFree:')
            idx3 = m.index('Buffers:')
            idx4 = m.index('Cached:')

            total = int(m[idx1 + 1])
            avail = int(m[idx2 + 1]) + int(m[idx3 + 1]) + int(m[idx4 + 1])

        return {
            'total': total * 1024,
            'used': (total - avail) * 1024
        }

    def _get_cpuinfo(self):
        cpuinfo = self._get_cpu_info()

        cpu_info = dict()

        cpu_info['arch'] = platform.uname()[5]
        cpu_info['model'] = cpuinfo.get('model name', 'unknown')
        cpu_info['vendor'] = cpuinfo.get('vendor id', 'unknown')

        topology = dict()
        topology['sockets'] = cpuinfo.get('socket(s)', 1)
        topology['cores'] = cpuinfo.get('core(s) per socket', 1)
        topology['threads'] = cpuinfo.get('thread(s) per core', 1)
        cpu_info['topology'] = topology
        cpu_info['features'] = cpuinfo.get('flags', 'unknown')

        return cpu_info

    def _get_cpu_info(self):
        '''Parse the output of lscpu.'''
        cpuinfo = {}
        out, err = utils.execute('lscpu')
        if err:
            msg = _('Unable to parse lscpu output.')
            raise exception.NovaException(msg)

        cpu = [line.strip('\n') for line in out.splitlines()]
        for line in cpu:
            if line.strip():
                name, value = line.split(':', 1)
                name = name.strip().lower()
                cpuinfo[name] = value.strip()

        f = open('/proc/cpuinfo', 'r')
        features = [line.strip('\n') for line in f.readlines()]
        for line in features:
            if line.strip():
                if line.startswith('flags'):
                    name, value = line.split(':', 1)
                    name = name.strip().lower()
                    cpuinfo[name] = value.strip()

        return cpuinfo
