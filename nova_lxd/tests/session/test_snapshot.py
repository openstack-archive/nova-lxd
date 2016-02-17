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
class SessionSnapshotTest(test.NoDBTestCase):

    def setUp(self):
        super(SessionSnapshotTest, self).setUp()

        """This is so we can mock out pylxd API calls."""
        self.ml = stubs.lxd_mock()
        lxd_patcher = mock.patch('pylxd.api.API',
                                 mock.Mock(return_value=self.ml))
        lxd_patcher.start()
        self.addCleanup(lxd_patcher.stop)

        self.session = session.LXDAPISession()

    @stubs.annotated_data(
        ('1,', (200, fake_api.fake_operation_info_ok()))
    )
    def test_container_snapshot(self, tag, side_effect):
        snapshot = mock.Mock()
        instance = stubs._fake_instance()
        self.ml.container_snapshot_create.return_value = side_effect
        self.assertEqual(None,
                         self.session.container_snapshot(snapshot, instance))
        calls = [
            mock.call.container_snapshot_create(instance.name, snapshot),
            mock.call.wait_container_operation(
                '/1.0/operation/1234', 200, -1)]
        self.assertEqual(calls, self.ml.method_calls)

    @stubs.annotated_data(
        ('api_fail', lxd_exceptions.APIError(500, 'Fake'),
         exception.NovaException)
    )
    def test_container_snapshot_fail(self, tag, side_effect, expected):
        snapshot = mock.Mock()
        instance = stubs._fake_instance()
        self.ml.container_snapshot_create.side_effect = side_effect
        self.assertRaises(expected,
                          self.session.container_snapshot,
                          instance.name, snapshot)

    @stubs.annotated_data(
        (1, (200, fake_api.fake_operation_info_ok()))
    )
    def test_container_publish(self, tag, side_effect):
        image = mock.Mock()
        instance = stubs._fake_instance()
        self.ml.image_export.return_value = True
        self.assertTrue(
            self.session.container_publish(image, instance))
        calls = [
            mock.call.container_publish(image)]
        self.assertEqual(calls, self.ml.method_calls)
