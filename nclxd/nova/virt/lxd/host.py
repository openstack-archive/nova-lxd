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
import platform

from oslo_config import cfg
from oslo_log import log as logging
from oslo_serialization import jsonutils
from oslo_utils import units

from nova.compute import arch
from nova.compute import hv_type
from nova.compute import utils as compute_utils
from nova.compute import vm_mode
from nova.i18n import _LW
from nova import utils

from cpuinfo import cpuinfo
import psutil

CONF = cfg.CONF
LOG = logging.getLogger(__name__)


class Host(object):
    def __init__(self, lxd):
        self.lxd = lxd
        self.host_cpu_info = cpuinfo.get_cpu_info()

    def get_available_resource(self, nodename):
        local_cpu_info = self._get_cpu_info()
        cpu_topology = local_cpu_info['topology']
        vcpus = (cpu_topology['cores'] *
                 cpu_topology['sockets'] *
                 cpu_topology['threads'])

        local_memory_info = self._get_memory_mb_usage()
        local_disk_info = self._get_fs_info(CONF.lxd.lxd_root_dir)

        data = {
            'vcpus': vcpus,
            'memory_mb': local_memory_info['total'] / units.Mi,
            'memory_mb_used': local_memory_info['used'] / units.Mi,
            'local_gb': local_disk_info['total'] / units.Gi,
            'local_gb_used': local_disk_info['used'] / units.Gi,
            'vcpus_used': 0,
            'hypervisor_type': 'lxd',
            'hypervisor_version': 1,
            'hypervisor_hostname': platform.node(),
            'supported_instances': jsonutils.dumps(
                   [(arch.I686, hv_type.LXC, vm_mode.EXE),
                    (arch.X86_64, hv_type.LXC, vm_mode.EXE)]),
            'numa_topology': None,
        }
        return data

    def get_host_ip_addr(self):
        ips = compute_utils.get_machine_ips()
        if CONF.my_ip not in ips:
            LOG.warn(_LW('my_ip address (%(my_ip)s) was not found on '
                     'any of the interfaces: %(ifaces)s'),
                     {'my_ip': CONF.my_ip, 'ifaces': ", ".join(ips)})
        return CONF.my_ip

    def get_host_uptime(self):
        out, err = utils.execute('env', 'LANG=C', 'uptime')
        return out

    def _get_fs_info(self, path):
        """get free/used/total space info for a filesystem
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
        "returns: the total usage of memory(MB)
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

    def _get_cpu_info(self):
        cpu_info = dict()

        cpu_info['arch'] = platform.uname()[5]
        cpu_info['model'] = self.host_cpu_info['brand']
        cpu_info['vendor'] = self.host_cpu_info['vendor_id']

        topology = dict()
        topology['sockets'] = self._get_cpu_sockets()
        topology['cores'] = self._get_cpu_cores()
        topology['threads'] = 1  # fixme
        cpu_info['topology'] = topology
        cpu_info['features'] = self.host_cpu_info['flags']

        return cpu_info

    def _get_cpu_cores(self):
        try:
            return psutil.cpu_count()
        except Exception:
            return psutil.NUM_CPUS

    def _get_cpu_sockets(self):
        try:
            return psutil.cpu_count(Logical=False)
        except Exception:
            return psutil.NUM_CPUS

    def get_host_cpu_stats(self):
        return {
            'kernel': long(psutil.cpu_times()[2]),
            'idle': long(psutil.cpu_times()[3]),
            'user': long(psutil.cpu_times()[0]),
            'iowait': long(psutil.cpu_times()[4]),
            'frequency': self.host_cpu_info['hz_advertised']
        }
