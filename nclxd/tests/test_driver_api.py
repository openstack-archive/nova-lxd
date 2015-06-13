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

from nova import context
from nova import test
from nova.virt import fake
from nova.tests.unit import fake_network
from nova.tests.unit import fake_instance
from nclxd.nova.virt.lxd import driver
from nova import exception
from nova import utils

from nclxd.nova.virt.lxd import container_ops

CONF = cfg.CONF

class LXDTestDriver(test.NoDBTestCase):
    def setUp(self):
        super(LXDTestDriver, self).setUp()
        self.connection = driver.LXDDriver(fake.FakeVirtAPI())

    def test_capabilities(self):
        self.assertFalse(self.connection.capabilities['has_imagecache'])
        self.assertFalse(self.connection.capabilities['supports_recreate'])
        self.assertFalse(self.connection.capabilities[
                        'supports_migrate_to_same_host'])

    @mock.patch.object(container_ops.LXDOperations, 'container_init_host')
    def test_init_host(self, mock_container_init):
        mock_container_init.side_affect = True
        self.assertTrue(self.connection.init_host("fakehost"))

    @mock.patch.object(container_ops.LXDOperations, 'container_init_host')
    def test_init_host_fail(self, mock_container_init):
        mock_container_init.side_affect = False
        self.assertFalse(self.connection.init_host("fakehost"))
