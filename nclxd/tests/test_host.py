# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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


import contextlib
import platform

import mock

from oslo_config import cfg
from oslo_utils import units

from nova import test
from nova.virt import fake
from nclxd.nova.virt.lxd import driver
from nclxd.nova.virt.lxd import host
from nova import utils

CONF = cfg.CONF

class LXDTestHostCase(test.NoDBTestCase):
    def setUp(self):
        super(LXDTestHostCase, self).setUp()
        self.connection = driver.LXDDriver(fake.FakeVirtAPI())

    def test_get_available_resource(self):
        memory = {
            'total': 4 * units.Mi,
            'used': 1 * units.Mi
        }

        disk = {
            'total': 10 * units.Gi,
            'available': 3 * units.Gi,
            'used': 1 * units.Gi
        }

        cpu_info = {
            'arch': 'x86_64',
            'model': 'Intel(R) Pentium(R) CPU  J2900  @ 2.41GHz',
            'vendor': 'GenuineIntel',
            'sockets': 1,
            'cores': 4,
            'threads': 1,
            'topology': {'sockets': 1,
                         'cores': 4,
                         'threads': 1
                         },
            'features': 'fpu vme de pse tsc msr pae mce cx8 apic sep mtrr pge mca cmov'
                        'pat pse36 clflush dts acpi mmx fxsr sse sse2 ss ht tm pbe '
                        'syscall nx rdtscp lm constant_tsc arch_perfmon pebs bts rep_'
                        'good nopl xtopology nonstop_tsc aperfmperf pni pclmul'
                        'qdq dtes64 monitor ds_cpl vmx est tm2 ssse3 cx16'
                        'xtpr pdcm sse4_1 sse4_2 movbe popcnt tsc_deadline_timer'
                        'rdrand lahf_lm 3dnowprefetch ida arat epb dtherm tpr_shadow'
                        ' vnmi flexpriority ept vpid tsc_adjust smep erms'
            }

        with contextlib.nested(
            mock.patch.object(host.Host, '_get_fs_info',
                              return_value=disk),
            mock.patch.object(host.Host, '_get_memory_mb_usage',
                              return_value=memory),
            mock.patch.object(host.Host, '_get_cpu_info',
                              return_value=cpu_info)
        ) as (
            _get_fs_info,
            _get_memory_mb_usage,
            _get_cpu_info
        ):
            stats = self.connection.get_available_resource("compute1")
            self.assertEquals(stats['vcpus'], 4)
            self.assertEquals(stats['memory_mb'], 4)
            self.assertEquals(stats['memory_mb_used'], 1)
            self.assertEquals(stats['local_gb'], 10)
            self.assertEquals(stats['local_gb_used'], 1)
            self.assertEquals(stats['vcpus_used'], 0)
            self.assertEquals(stats['hypervisor_type'], 'lxd')
            self.assertEquals(stats['hypervisor_version'], 1)
            self.assertEquals(stats['hypervisor_hostname'], platform.node())

    def test_get_host_ip_addr(self):
        ip = self.connection.get_host_ip_addr()
        self.assertEqual(ip, CONF.my_ip)

    #@mock.patch('nova.utils.execute')
    #def test_get_host_uptime(self, mock_execute):
    #    self.connection.get_host_uptime()
    #    mock_execute.assert_has_calls([
    #        mock.call('env', 'LANG=C', 'uptime')])
