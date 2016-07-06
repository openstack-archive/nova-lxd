# Copyright 2016 Canonical Ltd
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
import mock
from nova import exception
from nova import test
from pylxd import exceptions as lxdcore_exceptions

from nova.virt.lxd import driver


class LXDDriverTest(test.NoDBTestCase):
    """Tests for nova.virt.lxd.driver.LXDDriver."""

    def setUp(self):
        super(LXDDriverTest, self).setUp()

        self.Client_patcher = mock.patch('nova.virt.lxd.driver.pylxd.Client')
        self.Client = self.Client_patcher.start()

        self.client = mock.Mock()
        self.Client.return_value = self.client

    def tearDown(self):
        super(LXDDriverTest, self).tearDown()
        self.Client_patcher.stop()

    def test_init_host(self):
        """init_host initializes the pylxd Client."""
        lxd_driver = driver.LXDDriver(None)
        lxd_driver.init_host(None)

        self.Client.assert_called_once_with()
        self.assertEqual(self.client, lxd_driver.client)

    def test_init_host_fail(self):
        def side_effect():
            raise lxdcore_exceptions.ClientConnectionFailed()
        self.Client.side_effect = side_effect
        self.Client.return_value = None

        lxd_driver = driver.LXDDriver(None)

        self.assertRaises(
            exception.HostNotFound,
            lxd_driver.init_host,
            None
        )
