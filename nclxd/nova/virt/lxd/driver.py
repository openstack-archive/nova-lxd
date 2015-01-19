# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
# Copyright (c) 2010 Citrix Systems, Inc.
# Copyright (c) 2015 Canonical Ltd.
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
Nova LXD Driver

"""

import socket
import contextlib
import multiprocessing

from oslo.utils import units

from oslo.config import cfg
from oslo.serialization import jsonutils


from nova.compute import power_state
from nova.compute import task_states
from nova.compute import vm_mode
from nova.console import type as ctype
from nova import db
from nova import exception
from nova.i18n import _LW
from nova.openstack.common import log as logging
from nova import utils
from nova.virt import diagnostics
from nova.virt import driver
from nova.virt import firewall
from nova.virt import hardware
from nova.virt import virtapi

from . import client
from . import container
from . import host_utils

lxd_opts = [
    cfg.StrOpt('lxd_client_cert',
               default='/etc/lxd/client.crt',
               help='LXD client certificate'),
    cfg.StrOpt('lxd_client_key',
               default='/etc/lxd/client.key',
               help='LXD client key'),
    cfg.StrOpt('lxd_client_host',
               default='127.0.0.1:8443',
               help='LXD API Server'),
    cfg.StrOpt('lxd_root_dir',
               default='/var/lib/lxd/lxc',
               help='Default LXD directory'),
    cfg.StrOpt('lxd_default_template',
               default='ubuntu-cloud',
               help='Default LXC template'),
    cfg.StrOpt('lxd_template_dir',
               default='/usr/share/lxc/templates',
               help='Default template directory'),
    cfg.StrOpt('lxd_config_dir',
               default='/usr/share/lxc/config',
               help='Default lxc config dir')
]


CONF = cfg.CONF
CONF.register_opts(lxd_opts, 'lxd')
CONF.import_opt('host', 'nova.netconf')

LOG = logging.getLogger(__name__)


class LXDDriver(driver.ComputeDriver):
    capabilities = {
        "has_imagecache": False,
        "supports_recreate": False,
    }

    """LXD hypervisor driver."""

    def __init__(self, virtapi, read_only=False):
        super(LXDDriver, self).__init__(virtapi)

        self.client = client.Client(CONF.lxd.lxd_client_host,
                                    CONF.lxd.lxd_client_cert,
                                    CONF.lxd.lxd_client_key)
        self.firewall_driver = firewall.load_driver(
            default='nova.virt.firewall.NoopFirewallDriver')
        self.container = container.Container(self.client,
                                             self.virtapi,
                                             self.firewall_driver)

    def init_host(self, host):
        return self.container.init_container()

    def list_instances(self):
        return self.client.list()

    def list_instance_uuids(self):
        return self.client.list()

    def spawn(self, context, instance, image_meta, injected_files,
              admin_password, network_info=None, block_device_info=None,
              flavor=None):
        self.container.start_container(context, instance, image_meta,
                                       injected_files, admin_password, network_info,
                                       block_device_info, flavor)

    def snapshot(self, context, instance, name, update_task_state):
        raise NotImplemented()

    def reboot(self, context, instance, network_info, reboot_type,
               block_device_info=None, bad_volumes_callback=None):
        self.client.reboot(instance['uuid'])

    def rescue(self, context, instance, network_info, image_meta,
               rescue_password):
        raise NotImplemented()

    def unrescue(self, instance, network_info):
        raise NotImplemented()

    def poll_rebooting_instances(self, timeout, instances):
        raise NotImplemented()

    def migrate_disk_and_power_off(self, context, instance, dest,
                                   flavor, network_info,
                                   block_device_info=None,
                                   timeout=0, retry_interval=0):
        raise NotImplemented()

    def finish_revert_migration(self, context, instance, network_info,
                                block_device_info=None, power_on=True):
        raise NotImplemented()

    def post_live_migration_at_destination(self, context, instance,
                                           network_info,
                                           block_migration=False,
                                           block_device_info=None):
        raise NotImplemented()

    def power_off(self, instance, shutdown_timeout=0, shutdown_attempts=0):
        self.client.stop(instance['uuid'])

    def power_on(self, context, instance, network_info, block_device_info):
        self.client.start(instance['uuid'])

    def soft_delete(self, instance):
        pass

    def restore(self, instance):
        raise NotImplemented()

    def pause(self, instance):
        self.client.pause(instance['uuid'])

    def unpause(self, instance):
        self.client.unpause(instance['uuid'])

    def suspend(self, instance):
        raise NotImplemented()

    def resume(self, context, instance, network_info, block_device_info=None):
        raise NotImplemented()

    def destroy(self, context, instance, network_info, block_device_info=None,
                destroy_disks=True, migrate_data=None):
        self.client.destroy(instance['uuid'])
        self.cleanup(context, instance, network_info, block_device_info)

    def cleanup(self, context, instance, network_info, block_device_info=None,
                destroy_disks=True, migrate_data=None, destroy_vifs=True):
        self.container.teardown_network(instance, network_info)

    def attach_volume(self, context, connection_info, instance, mountpoint,
                      disk_bus=None, device_type=None, encryption=None):
        """Attach the disk to the instance at mountpoint using info."""
        raise NotImplemented()

    def detach_volume(self, connection_info, instance, mountpoint,
                      encryption=None):
        """Detach the disk attached to the instance."""
        raise NotImplemented()

    def swap_volume(self, old_connection_info, new_connection_info,
                    instance, mountpoint, resize_to):
        """Replace the disk attached to the instance."""
        raise NotImplemented()

    def attach_interface(self, instance, image_meta, vif):
        raise NotImplemented()

    def detach_interface(self, instance, vif):
        raise NotImplemented()

    def get_info(self, instance):
        if self.client.running(instance['uuid']):
            pstate = power_state.RUNNING
        else:
            pstate = power_state.SHUTDOWN
        return hardware.InstanceInfo(state=pstate,
                                     max_mem_kb=0,
                                     mem_kb=0,
                                     num_cpu=2,
                                     cpu_time_ns=0)

    def get_console_output(self, context, instance):
        return self.container.get_console_log(instance)

    def refresh_security_group_rules(self, security_group_id):
        self.firewall_driver.refresh_security_group_rules(security_group_id)

    def refresh_security_group_members(self, security_group_id):
        self.firewall_driver.refresh_security_group_members(security_group_id)

    def refresh_instance_security_rules(self, instance):
        self.firewall_driver.refresh_rules(instance)

    def refresh_provider_fw_rules(self):
        self.firewall_driver.refresh_provider_fw_rules()

    def get_available_resource(self, nodename):
        """Updates compute manager resource info on ComputeNode table.

           Since we don't have a real hypervisor, pretend we have lots of
           disk and ram.
        """
        data = {}
        disk = host_utils.get_fs_info(CONF.lxd.lxd_root_dir)
        memory = host_utils.get_memory_mb_usage()

        data["supported_instances"] = jsonutils.dumps([
            ('i686', 'lxd', 'lxd'),
            ('x86_64', 'lxd', 'lxd')])
        data["vcpus"] = multiprocessing.cpu_count()
        data["memory_mb"] = memory['total'] / units.Mi
        data["local_gb"] = disk['total'] / units.Gi
        data["vcpus_used"] = 1
        data["memory_mb_used"] = memory['used'] / units.Mi
        data["local_gb_used"] = disk['used'] / units.Gi
        data["hypervisor_type"] = "lxd"
        data["hypervisor_version"] = "1.0"
        data["hypervisor_hostname"] = nodename
        data["cpu_info"] = "?"
        data["disk_available_least"] = disk['free'] / units.Gi
        data['numa_topology'] = None

        return data

    def ensure_filtering_rules_for_instance(self, instance_ref, network_info):
        self.firewall_driver.setup_basic_filtering(instance_ref, network_info)
        self.firewall_driver.prepare_instance_filter(
            instance_ref, network_info)

    def unfilter_instance(self, instance, network_info):
        self.firewall_driver.unfilter_instance(instance, network_info)

    def get_available_nodes(self, refresh=False):
        hostname = socket.gethostname()
        return [hostname]
