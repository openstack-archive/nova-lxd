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
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
#    implied. See the License for the specific language governing
#    permissions and limitations under the License.

import ddt
import mock

from nova import test

from nova_lxd.nova.virt.lxd import session
from nova_lxd.tests import stubs


@ddt.ddt
class SessionEventTest(test.NoDBTestCase):

    def setUp(self):
        super(SessionEventTest, self).setUp()

        self.ml = stubs.lxd_mock()
        lxd_patcher = mock.patch('pylxd.api.API',
                                 mock.Mock(return_value=self.ml))
        lxd_patcher.start()
        self.addCleanup(lxd_patcher.stop)

        self.session = session.LXDAPISession()

    def test_container_wait(self):
        instance = stubs._fake_instance()
        operation_id = mock.Mock()
        self.ml.wait_container_operation.return_value = True
        self.assertEqual(None,
                         self.session.operation_wait(operation_id, instance))
        self.ml.wait_container_operation.assert_called_with(operation_id,
                                                            200, -1)
