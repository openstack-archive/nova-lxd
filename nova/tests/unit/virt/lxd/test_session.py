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

"""
Unit tests for ContinerMixin class

The following tests the ContainerMixin class
for nova-lxd.
"""

import ddt
import mock

from nova import exception
from nova import test
from pylxd.deprecated import exceptions as lxd_exceptions

from nova.virt.lxd import session
import fake_api
import stubs


@ddt.ddt
class SessionContainerTest(test.NoDBTestCase):

    def setUp(self):
        super(SessionContainerTest, self).setUp()

        """This is so we can mock out pylxd API calls."""
        self.ml = stubs.lxd_mock()
        lxd_patcher = mock.patch('pylxd.deprecated.api.API',
                                 mock.Mock(return_value=self.ml))
        lxd_patcher.start()
        self.addCleanup(lxd_patcher.stop)

        self.session = session.LXDAPISession()

    @stubs.annotated_data(
        ('1', (200, fake_api.fake_operation_info_ok()))
    )
    def test_container_init(self, tag, side_effect):
        """
        conatainer_init creates a container based on given config
        for a container. Check to see if we are returning the right
        pylxd calls for the LXD API.
        """
        config = mock.Mock()
        instance = stubs._fake_instance()
        self.ml.container_init.return_value = side_effect
        self.ml.operation_info.return_value = \
            (200, fake_api.fake_container_state(200))
        self.assertIsNone(self.session.container_init(config, instance))
        calls = [mock.call.container_init(config),
                 mock.call.wait_container_operation(
                     '/1.0/operation/1234', 200, -1),
                 mock.call.operation_info('/1.0/operation/1234')]
        self.assertEqual(calls, self.ml.method_calls)

    @stubs.annotated_data(
        ('api_fail', lxd_exceptions.APIError(500, 'Fake'),
         exception.NovaException),
    )
    def test_container_init_fail(self, tag, side_effect, expected):
        """
        continer_init create as container on a given LXD host. Make
        sure that we reaise an exception.NovaException if there is
        an APIError from the LXD API.
        """
        config = mock.Mock()
        instance = stubs._fake_instance()
        self.ml.container_init.side_effect = side_effect
        self.assertRaises(expected,
                          self.session.container_init, config,
                          instance)


@ddt.ddt
class SessionEventTest(test.NoDBTestCase):

    def setUp(self):
        super(SessionEventTest, self).setUp()

        self.ml = stubs.lxd_mock()
        lxd_patcher = mock.patch('pylxd.deprecated.api.API',
                                 mock.Mock(return_value=self.ml))
        lxd_patcher.start()
        self.addCleanup(lxd_patcher.stop)

        self.session = session.LXDAPISession()

    def test_container_wait(self):
        instance = stubs._fake_instance()
        operation_id = mock.Mock()
        self.ml.wait_container_operation.return_value = True
        self.assertIsNone(self.session.operation_wait(operation_id, instance))
        self.ml.wait_container_operation.assert_called_with(operation_id,
                                                            200, -1)
