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

import ddt
import mock
from nova.compute import power_state
from nova import exception
from nova import test
from nova.virt import fake
from nova.virt import hardware
from oslo_config import cfg
from pylxd import exceptions as lxd_exceptions

from nclxd.nova.virt.lxd import container_ops
from nclxd.nova.virt.lxd import container_utils
from nclxd.nova.virt.lxd import driver
from nclxd import tests


class LXDTestConfig(test.NoDBTestCase):

    def test_config(self):
        self.assertIsInstance(driver.CONF.lxd, cfg.ConfigOpts.GroupAttr)
        self.assertEqual(os.path.abspath('/var/lib/lxd'),
                         os.path.abspath(driver.CONF.lxd.root_dir))
        self.assertEqual(5, driver.CONF.lxd.timeout)
        self.assertEqual('nclxd-profile', driver.CONF.lxd.default_profile)


@ddt.ddt
@mock.patch.object(container_ops, 'CONF', tests.MockConf())
@mock.patch.object(container_utils, 'CONF', tests.MockConf())
@mock.patch.object(driver, 'CONF', tests.MockConf())
class LXDTestDriver(test.NoDBTestCase):

    @mock.patch.object(driver, 'CONF', tests.MockConf())
    def setUp(self):
        super(LXDTestDriver, self).setUp()
        self.ml = tests.lxd_mock()
        lxd_patcher = mock.patch('pylxd.api.API',
                                 mock.Mock(return_value=self.ml))
        lxd_patcher.start()
        self.addCleanup(lxd_patcher.stop)

        self.connection = driver.LXDDriver(fake.FakeVirtAPI())

    def test_capabilities(self):
        self.assertFalse(self.connection.capabilities['has_imagecache'])
        self.assertFalse(self.connection.capabilities['supports_recreate'])
        self.assertFalse(
            self.connection.capabilities['supports_migrate_to_same_host'])

    def test_init_host(self):
        self.assertEqual(
            True,
            self.connection.init_host(None)
        )

    def test_init_host_new_profile(self):
        self.ml.profile_list.return_value = []
        self.assertEqual(
            True,
            self.connection.init_host(None)
        )
        self.ml.profile_create.assert_called_once_with(
            {'name': 'fake_profile'})

    @tests.annotated_data(
        ('profile_fail', {'profile_list.side_effect':
                          lxd_exceptions.APIError('Fake', 500)}),
        ('no_ping', {'host_ping.return_value': False}),
        ('ping_fail', {'host_ping.side_effect':
                       lxd_exceptions.APIError('Fake', 500)}),
    )
    def test_init_host_fail(self, tag, config):
        self.ml.configure_mock(**config)
        self.assertRaises(
            exception.HostNotFound,
            self.connection.init_host,
            None
        )

    @tests.annotated_data(
        ('RUNNING', power_state.RUNNING),
        ('STOPPED', power_state.SHUTDOWN),
        ('STARTING', power_state.NOSTATE),
        ('STOPPING', power_state.SHUTDOWN),
        ('ABORTING', power_state.CRASHED),
        ('FREEZING', power_state.PAUSED),
        ('FROZEN', power_state.SUSPENDED),
        ('THAWED', power_state.PAUSED),
        ('PENDING', power_state.NOSTATE),
        ('Success', power_state.RUNNING),
        ('UNKNOWN', power_state.NOSTATE),
        (lxd_exceptions.APIError('Fake', 500), power_state.NOSTATE),
    )
    def test_get_info(self, side_effect, expected):
        instance = tests.MockInstance()
        self.ml.container_state.side_effect = [side_effect]
        self.assertEqual(hardware.InstanceInfo(state=expected, num_cpu=2),
                         self.connection.get_info(instance))

    @tests.annotated_data(
        (True, 'mock-instance-1'),
        (False, 'fake-instance'),
    )
    def test_instance_exists(self, expected, name):
        self.assertEqual(
            expected,
            self.connection.instance_exists(tests.MockInstance(name=name)))

    def test_estimate_instance_overhead(self):
        self.assertEqual(
            {'memory_mb': 0},
            self.connection.estimate_instance_overhead(mock.Mock()))

    def test_list_instances(self):
        self.assertEqual(['mock-instance-1', 'mock-instance-2'],
                         self.connection.list_instances())

    def test_list_instances_fail(self):
        self.ml.container_list.side_effect = (
            lxd_exceptions.APIError('Fake', 500))
        self.assertRaises(
            exception.NovaException,
            self.connection.list_instances
        )


@ddt.ddt
class LXDTestDriverNoops(test.NoDBTestCase):

    def setUp(self):
        super(LXDTestDriverNoops, self).setUp()
        self.connection = driver.LXDDriver(fake.FakeVirtAPI())

    @ddt.data(
        'list_instance_uuids',
    )
    def test_notimplemented(self, method):
        self.assertRaises(
            NotImplementedError,
            getattr(self.connection, method))
