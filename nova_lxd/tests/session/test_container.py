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

from nova.compute import power_state
from nova import exception
from nova import test
from pylxd import exceptions as lxd_exceptions

from nova_lxd.nova.virt.lxd.session import session
from nova_lxd.tests import fake_api
from nova_lxd.tests import stubs

"""
Unit tests for ContinerMixin class

The following tests the ContainerMixin class
for nova-lxd.
"""


@ddt.ddt
class SessionContainerTest(test.NoDBTestCase):

    def setUp(self):
        super(SessionContainerTest, self).setUp()

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
    def test_container_list(self, tag, side_effect, expected):
        """Test container list."""
        self.ml.container_list.return_value = side_effect
        self.assertEqual(expected,
                         self.session.container_list())

    def test_container_list_fail(self):
        """Test container_list fail."""
        self.ml.container_list.side_effect = (
            lxd_exceptions.APIError('Fake', 500))
        self.assertRaises(
            exception.NovaException,
            self.session.container_list)

    def test_container_update(self):
        """Test container update."""
        config = mock.Mock()
        instance = stubs._fake_instance()
        self.ml.container_update.return_value = \
            (200, fake_api.fake_container_config())
        self.assertEqual((200, fake_api.fake_container_config()),
                         self.session.container_update(config, instance))
        calls = [
            mock.call.container_defined(instance.name),
            mock.call.container_update(instance.name, config)]
        self.assertEqual(calls, self.ml.method_calls)

    @stubs.annotated_data(
        ('api_fail', True, lxd_exceptions.APIError('Fake', 500),
         exception.NovaException),
        ('missing_container', False, None,
         exception.InstanceNotFound)
    )
    def test_container_update_fail(self, tag, container_defined, side_effect,
                                   expected):
        """Test container update fail."""
        config = mock.Mock()
        instance = stubs._fake_instance()
        if container_defined:
            self.ml.container_defined.return_value = container_defined
            self.ml.container_update.side_effect = (
                lxd_exceptions.APIError('Fake', 500))
            self.assertRaises(
                expected,
                self.session.container_update, config, instance)
        if not container_defined:
            self.ml.container_defined.return_value = container_defined
            self.assertRaises(
                expected,
                self.session.container_update, config, instance)

    @stubs.annotated_data(
        ('running', True),
        ('idle', False),
        ('api_failure', lxd_exceptions.APIError('Fake', '500')),
    )
    def test_container_running(self, tag, side_effect):
        """Test container_running function."""
        instance = stubs._fake_instance()
        if side_effect:
            self.ml.container_running.return_value = side_effect
            self.assertTrue(self.session.container_running(instance))
        if not side_effect:
            self.ml.container_running.return_value = side_effect
            self.assertFalse(self.session.container_running(instance))
        if tag == 'api_failure':
            self.ml.container_running.side_effect = side_effect
            self.assertRaises(
                exception.NovaException,
                self.session.container_running, instance
            )

    @stubs.annotated_data(
        ('running', (200, fake_api.fake_container_state(200)),
         power_state.RUNNING),
        ('crashed', (200, fake_api.fake_container_state(108)),
         power_state.CRASHED),
    )
    def test_container_state(self, tag, side_effect, expected):
        """Test container state function."""
        instance = stubs._fake_instance()
        self.ml.container_state.return_value = side_effect
        self.assertEqual(expected,
                         self.session.container_state(instance))

    @stubs.annotated_data(
        ('api_fail', True, lxd_exceptions.APIError('Fake', 500),
         power_state.NOSTATE),
        ('missing', False, None, power_state.NOSTATE)
    )
    def test_container_state_fail(self, tag, container_defined, side_effect,
                                  expected):
        """Test container state fail."""
        instance = stubs._fake_instance()
        if container_defined:
            self.ml.container_defined.return_value = container_defined
            self.ml.container_state.side_effect = (
                lxd_exceptions.APIError('Fake', 500))
            self.assertEqual(
                expected,
                self.session.container_state(instance))
        if not container_defined:
            self.ml.container_defined.return_value = container_defined
            self.assertEqual(
                expected,
                self.session.container_state(instance))

    def test_container_config(self):
        """Test container_config function."""
        instance = stubs._fake_instance()
        self.ml.get_container_config.return_value = \
            (200, fake_api.fake_container_config())
        self.assertEqual(
            (200, fake_api.fake_container_config()),
            self.session.container_config(instance))

    @stubs.annotated_data(
        ('api_fail', True, lxd_exceptions.APIError('Fake', 500),
         exception.NovaException),
    )
    def test_container_config_fail(self, tag, container_defined, side_effect,
                                   expected):
        """Test container_config fail."""
        instance = stubs._fake_instance()
        if container_defined:
            self.ml.container_defined.return_value = container_defined
            self.ml.get_container_config.side_effect = side_effect
            self.assertRaises(
                expected,
                self.session.container_config, instance)

    def test_container_info(self):
        """Test container_info function."""
        instance = stubs._fake_instance()
        self.ml.container_info.return_value = \
            (200, fake_api.fake_container_info())
        self.assertEqual(
            (200, fake_api.fake_container_info()),
            self.session.container_info(instance))

    def test_container_info_fail(self):
        " Test container_info funciton fail."""
        instance = stubs._fake_instance()
        self.ml.container_info.side_effect = (
            lxd_exceptions.APIError('Fake', 500))
        self.assertRaises(
            exception.NovaException,
            self.session.container_info, instance)

    @stubs.annotated_data(
        ('exists', True),
        ('missing', False),
    )
    def test_container_defined(self, tag, side_effect):
        """Test container_defined function."""
        instance = stubs._fake_instance()
        self.ml.container_defined.return_value = side_effect
        if side_effect:
            self.assertTrue(self.session.container_defined(
                instance.name, instance))
        if not side_effect:
            self.assertFalse(self.session.container_defined(
                instance.name, instance))

    @stubs.annotated_data(
        ('1', True, (200, fake_api.fake_operation_info_ok()))
    )
    def test_container_start(self, tag, defined, side_effect=None):
        """Test container_start function."""
        instance = stubs._fake_instance()
        self.ml.container_defined.return_value = defined
        self.ml.container_start.return_value = side_effect
        self.assertEqual(None,
                         self.session.container_start(instance.name,
                                                      instance))
        calls = [mock.call.container_defined(instance.name),
                 mock.call.container_start(instance.name, 5),
                 mock.call.wait_container_operation(
            '/1.0/operation/1234', 200, -1)]
        self.assertEqual(calls, self.ml.method_calls)

    @stubs.annotated_data(
        ('container_missing', False,
         exception.InstanceNotFound),
        ('api_error', True,
         exception.NovaException,
         lxd_exceptions.APIError('Fake', 500)),
    )
    def test_container_start_fail(self, tag, container_defined,
                                  expected, side_effect=None):
        """Test container start function to fail."""
        instance = stubs._fake_instance()
        if container_defined:
            self.ml.container_defined.return_value = container_defined
            self.ml.container_start.side_effect = side_effect
            self.assertRaises(expected,
                              self.session.container_start,
                              instance.name, instance)
        if not container_defined:
            self.ml.container_defined.return_value = container_defined
            self.assertRaises(expected,
                              self.session.container_start, instance.name,
                              instance)

    @stubs.annotated_data(
        ('1', (200, fake_api.fake_operation_info_ok()))
    )
    def test_container_stop(self, tag, side_effect):
        """Test conainer_stop function."""
        instance = stubs._fake_instance()
        self.ml.container_stop.return_value = side_effect
        self.assertEqual(None,
                         self.session.container_stop(instance.name,
                                                     instance.host, instance))
        calls = [mock.call.container_defined(instance.name),
                 mock.call.container_stop(instance.name, 5),
                 mock.call.wait_container_operation(
            '/1.0/operation/1234', 200, -1)]
        self.assertEqual(calls, self.ml.method_calls)

    @stubs.annotated_data(
        ('api_fail', lxd_exceptions.APIError('Fake', 500),
         exception.NovaException)
    )
    def test_container_stop_fail(self, tag, side_effect, expected):
        """Test container_stop funciton to fail."""
        instance = stubs._fake_instance()
        self.ml.container_stop.side_effect = side_effect
        self.assertRaises(expected,
                          self.session.container_stop, instance.name,
                          instance.host, instance)

    @stubs.annotated_data(
        ('1,', (200, fake_api.fake_operation_info_ok()))
    )
    def test_continer_reboot(self, tag, side_effect):
        """Test container_reboot function."""
        instance = stubs._fake_instance()
        self.ml.container_reboot.return_value = side_effect
        self.assertEqual(None,
                         self.session.container_reboot(instance))
        calls = [mock.call.container_defined(instance.name),
                 mock.call.container_reboot(instance.name, 5),
                 mock.call.wait_container_operation(
                     '/1.0/operation/1234', 200, -1)]
        self.assertEqual(calls, self.ml.method_calls)

    @stubs.annotated_data(
        ('api_fail', lxd_exceptions.APIError('Fake', 500),
         exception.NovaException)
    )
    def test_container_reboot_fail(self, tag, side_effect, expected):
        """Test container_reboot function to fail."""
        instance = stubs._fake_instance()
        self.ml.container_reboot.side_effect = side_effect
        self.assertRaises(expected,
                          self.session.container_reboot, instance)

    @stubs.annotated_data(
        ('exists', True, (200, fake_api.fake_operation_info_ok())),
        ('missing', False, (200, fake_api.fake_operation_info_ok()))
    )
    def test_container_destroy(self, tag, container_defined, side_effect):
        """Test container_destroy function."""
        instance = stubs._fake_instance()
        if container_defined:
            self.ml.container_defined.return_value = container_defined
            self.ml.container_stop.return_value = side_effect
            self.ml.container_destroy.return_value = side_effect
            self.assertEqual(None,
                             self.session.container_destroy(instance.name,
                                                            instance.host,
                                                            instance))
            calls = [mock.call.container_defined(instance.name),
                     mock.call.container_defined(instance.name),
                     mock.call.container_stop(instance.name, 5),
                     mock.call.wait_container_operation(
                '/1.0/operation/1234', 200, -1),
                mock.call.container_destroy(instance.name),
                mock.call.wait_container_operation(
                '/1.0/operation/1234', 200, -1)]
            self.assertEqual(calls, self.ml.method_calls)
        if not container_defined:
            self.ml.container_defined.return_value = container_defined
            self.assertEqual(None,
                             self.session.container_destroy(instance.name,
                                                            instance.host,
                                                            instance))
            calls = [mock.call.container_defined(instance.name)]
            self.assertEqual(calls, self.ml.method_calls)

    @stubs.annotated_data(
        ('fail_to_stop', True, 'fail_stop',
         lxd_exceptions.APIError('Fake', '500'), exception.NovaException),
        ('fail_to_destroy', True, 'fail_destroy',
         lxd_exceptions.APIError('Fake', '500'), exception.NovaException)
    )
    def test_container_destroy_fail(self, tag, container_defined,
                                    test_type, side_effect, expected):
        """Test container_destroy function to fail."""
        instance = stubs._fake_instance()
        self.ml.cotnainer_defined.return_value = container_defined
        if test_type == 'fail_stop':
            self.ml.container_stop.side_effect = side_effect
            self.assertRaises(expected,
                              self.session.container_destroy, instance.name,
                              instance.host, instance)
        if test_type == 'fail_destroy':
            self.ml.container_defined.return_value = container_defined
            self.ml.container_stop.return_value = \
                (200, fake_api.fake_operation_info_ok())
            self.ml.container_destroy.side_effect = side_effect
            self.assertRaises(expected,
                              self.session.container_destroy, instance.name,
                              instance.host, instance)

    @stubs.annotated_data(
        ('1', (200, fake_api.fake_operation_info_ok()))
    )
    def fake_container_pause(self, tag, side_effect):
        """test container_pause function."""
        instance = stubs._fake_instance()
        self.ml.container_suspend.return_value = side_effect
        self.assertEqual(None,
                         self.session.container_pause(instance.name,
                                                      instance))
        calls = [
            mock.call.container_susepnd(instance.name, 5),
            mock.call.wait_container_operation(
                '/1.0/operation/1234', 200, -1)]
        self.assertEqual(calls, self.ml.method_calls)

    @stubs.annotated_data(
        ('api_fail', lxd_exceptions.APIError(500, 'Fake'),
         exception.NovaException)
    )
    def test_container_pause_fail(self, tag, side_effect, expected):
        """test container_pause function to fail."""
        instance = stubs._fake_instance()
        instance = stubs._fake_instance()
        self.ml.container_suspend.side_effect = side_effect
        self.assertRaises(expected,
                          self.session.container_pause,
                          instance.name, instance)

    @stubs.annotated_data(
        ('1', (200, fake_api.fake_operation_info_ok()))
    )
    def test_container_unpause(self, tag, side_effect):
        """test container_unpause function."""
        instance = stubs._fake_instance()
        self.ml.container_resume.return_value = side_effect
        self.assertEqual(None,
                         self.session.container_unpause(instance.name,
                                                        instance))
        calls = [
            mock.call.container_defined(instance.name),
            mock.call.container_resume(instance.name, 5),
            mock.call.wait_container_operation(
                '/1.0/operation/1234', 200, -1)]
        self.assertEqual(calls, self.ml.method_calls)

    @stubs.annotated_data(
        ('api_fail', lxd_exceptions.APIError(500, 'Fake'),
         exception.NovaException)
    )
    def test_container_unpause_fail(self, tag, side_effect, expected):
        """test container_unpause function to fail."""
        instance = stubs._fake_instance()
        self.ml.container_resume.side_effect = side_effect
        self.assertRaises(expected,
                          self.session.container_unpause,
                          instance.name, instance)

    @stubs.annotated_data(
        ('1', (200, fake_api.fake_operation_info_ok()))
    )
    def test_container_init(self, tag, side_effect):
        """test container_init function."""
        config = mock.Mock()
        instance = stubs._fake_instance()
        self.ml.container_init.return_value = side_effect
        self.ml.operation_info.return_value = \
            (200, fake_api.fake_container_state(200))
        self.assertEqual(None,
                         self.session.container_init(config, instance,
                                                     instance.host))
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
        """test container_init function to fail."""
        config = mock.Mock()
        instance = stubs._fake_instance()
        self.ml.container_init.side_effect = side_effect
        self.assertRaises(expected,
                          self.session.container_init, config,
                          instance, instance.host)
