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
from nova import exception
from nova import test
from nova.virt import fake
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
