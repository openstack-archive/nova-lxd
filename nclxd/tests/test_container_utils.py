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


import mock

from nova import exception
from nova import test

from nclxd.nova.virt.lxd import container_utils
from nclxd.tests import stubs


class LXDTestContainerUtils(test.NoDBTestCase):

    def setUp(self):
        super(LXDTestContainerUtils, self).setUp()
        self.ml = stubs.lxd_mock()
        lxd_patcher = mock.patch('pylxd.api.API',
                                 mock.Mock(return_value=self.ml))
        lxd_patcher.start()
        self.addCleanup(lxd_patcher.stop)

        self.container_utils = container_utils.LXDContainerUtils()

    def test_wait_undefined(self):
        self.assertRaises(exception.NovaException,
                          self.container_utils.wait_for_container,
                          None)

    def test_wait_timedout(self):
        self.ml.wait_container_operation.return_value = False
        self.assertRaises(exception.NovaException,
                          self.container_utils.wait_for_container,
                          'fake')
