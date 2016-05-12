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


from nova.compute import arch
from nova.compute import hv_type
from nova.compute import utils as compute_utils
from nova.compute import vm_mode
from nova import exception
from nova import i18n
from nova import utils
import os
import platform
from pylxd.deprecated import api
from pylxd.deprecated import exceptions as lxd_exceptions
import socket

from oslo_config import cfg
from oslo_log import log as logging
from oslo_serialization import jsonutils
from oslo_utils import units
import psutil

_ = i18n._
_LW = i18n._LW
CONF = cfg.CONF
LOG = logging.getLogger(__name__)


class LXDHost(object):

    def __init__(self):
        self.lxd = api.API()

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

    def _get_hypersivor_version(self):
        version = self.lxd.get_lxd_version()
        return '.'.join(str(v) for v in version)

    def get_host_cpu_stats(self):
        cpuinfo = self._get_cpu_info()
        return {
            'kernel': int(psutil.cpu_times()[2]),
            'idle': int(psutil.cpu_times()[3]),
            'user': int(psutil.cpu_times()[0]),
            'iowait': int(psutil.cpu_times()[4]),
            'frequency': cpuinfo.get('cpu mhz', 0)
        }

    def init_host(self, host):
        LOG.debug('Host check')
        try:
            if not self.lxd.host_ping():
                msg = _('Unable to connect to LXD daemon')
                raise exception.HostNotFound(msg)

            return True
        except lxd_exceptions.APIError as ex:
            msg = _('Unable to connect to LXD daemon: %s') % ex
            raise exception.HostNotFound(msg)
