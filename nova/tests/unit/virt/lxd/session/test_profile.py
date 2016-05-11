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

from nova import exception
from nova import test
from pylxd.deprecated import exceptions as lxd_exceptions

from nova_lxd.nova.virt.lxd import session
from nova_lxd.tests import fake_api
from nova_lxd.tests import stubs


@ddt.ddt
class SessionProfileTest(test.NoDBTestCase):

    def setUp(self):
        super(SessionProfileTest, self).setUp()

        """This is so we can mock out pylxd API calls."""
        self.ml = stubs.lxd_mock()
        lxd_patcher = mock.patch('pylxd.api.API',
                                 mock.Mock(return_value=self.ml))
        lxd_patcher.start()
        self.addCleanup(lxd_patcher.stop)

        self.session = session.LXDAPISession()

    @stubs.annotated_data(
        ('empty', [], []),
        ('valid', ['test'], ['test']),
    )
    def test_profile_list(self, tag, side_effect, expected):
        self.ml.profile_list.return_value = side_effect
        self.assertEqual(expected,
                         self.session.profile_list())

    def test_profile_list_fail(self):
        self.ml.profile_list.side_effect = (
            lxd_exceptions.APIError('Fake', 500))
        self.assertRaises(
            exception.NovaException,
            self.session.profile_list)

    def test_profile_create(self):
        instance = stubs._fake_instance()
        config = mock.Mock()
        self.ml.profile_defined.return_value = True
        self.ml.profile_create.return_value = \
            (200, fake_api.fake_standard_return())
        self.assertEqual((200, fake_api.fake_standard_return()),
                         self.session.profile_create(config,
                                                     instance))
        calls = [mock.call.profile_list(),
                 mock.call.profile_create(config)]
        self.assertEqual(calls, self.ml.method_calls)

    def test_profile_delete(self):
        instance = stubs._fake_instance()
        self.ml.profile_defined.return_value = True
        self.ml.profile_delete.return_value = \
            (200, fake_api.fake_standard_return())
        self.assertEqual(None,
                         self.session.profile_delete(instance))
