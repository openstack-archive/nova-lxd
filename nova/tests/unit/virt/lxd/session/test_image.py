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
class SessionImageTest(test.NoDBTestCase):

    def setUp(self):
        super(SessionImageTest, self).setUp()

        self.ml = stubs.lxd_mock()
        lxd_patcher = mock.patch('pylxd.api.API',
                                 mock.Mock(return_value=self.ml))
        lxd_patcher.start()
        self.addCleanup(lxd_patcher.stop)

        self.session = session.LXDAPISession()

    def test_image_defined(self):
        """Test the image is defined in the LXD hypervisor."""
        instance = stubs._fake_instance()
        self.ml.alias_defined.return_value = True
        self.assertTrue(self.session.image_defined(instance))
        calls = [mock.call.alias_defined(instance.image_ref)]
        self.assertEqual(calls, self.ml.method_calls)

    def test_alias_create(self):
        """Test the alias is created."""
        instance = stubs._fake_instance()
        alias = mock.Mock()
        self.ml.alias_create.return_value = True
        self.assertTrue(self.session.create_alias(alias, instance))
        calls = [mock.call.alias_create(alias)]
        self.assertEqual(calls, self.ml.method_calls)
