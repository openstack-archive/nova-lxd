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
        lxd_patcher = mock.patch('pylxd.api.API',
                                 mock.Mock(return_value=self.ml))
        lxd_patcher.start()
        self.addCleanup(lxd_patcher.stop)

        self.session = session.LXDAPISession()

    def test_container_update(self):
        """
        container_update updates the LXD container configuration,
        so verify that the correct pylxd calls are made.
        """
        config = mock.Mock()
        instance = stubs._fake_instance()
        self.ml.container_update.return_value = \
            (200, fake_api.fake_container_config())
        self.assertEqual((200, fake_api.fake_container_config()),
                         self.session.container_update(config, instance))
        calls = [
            mock.call.container_update(instance.name, config)]
        self.assertEqual(calls, self.ml.method_calls)

    @stubs.annotated_data(
        ('api_fail', lxd_exceptions.APIError('Fake', 500),
         exception.NovaException),
    )
    def test_container_update_fail(self, tag, side_effect,
                                   expected):
        """
        container_update will fail if the container is not found, or the
        LXD raises an API error. Verify that the exceptions are raised
        in both scenarios.
        """
        config = mock.Mock()
        instance = stubs._fake_instance()
        self.ml.container_update.side_effect = (
            lxd_exceptions.APIError('Fake', 500))
        self.assertRaises(
            expected,
            self.session.container_update, config, instance)

    @stubs.annotated_data(
        ('running', True),
        ('idle', False),
        ('api_failure', lxd_exceptions.APIError('Fake', '500')),
    )
    def test_container_running(self, tag, side_effect):
        """
        container_running determines if the container is running
        or not. Verify that we are returning True if the container
        is running. False if its not, raise an exception if there
        is an API error.
        """
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

    def test_container_config(self):
        """
        container_config returns a dictionary representation
        of the LXD container. Verify that the funciton returns
        a container_config
        """
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
        """
        container_config returns a dictionary represeation of the
        LXD container. Verify that the function raises an
        exception.NovaException when there is a APIError.
        """
        instance = stubs._fake_instance()
        if container_defined:
            self.ml.container_defined.return_value = container_defined
            self.ml.get_container_config.side_effect = side_effect
            self.assertRaises(
                expected,
                self.session.container_config, instance)

    def test_container_info(self):
        """
        container_info returns a dictonary represenation of
        useful information about a container, (ip address, pid, etc).
        Verify that the function returns the approiate dictionary
        representation for the LXD API.
        """
        instance = stubs._fake_instance()
        self.ml.container_info.return_value = \
            (200, fake_api.fake_container_info())
        self.assertEqual(
            (200, fake_api.fake_container_info()),
            self.session.container_info(instance))

    def test_container_info_fail(self):
        """
        container_info returns a dictionary reprsentation of
        userful information about a container (ip address, pid, etc).
        Verify that the container_info returns an exception.NovaException
        when there is an APIError.
        """
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
        """
        container_defined returns True if the container
        exists on an LXD host, False otherwise, verify
        the apporiate return value is returned.
        """
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
        """
        containser_start starts a container on a given LXD host.
        Verify that the correct pyLXD calls are made.
        """
        instance = stubs._fake_instance()
        self.ml.container_start.return_value = side_effect
        self.assertEqual(None,
                         self.session.container_start(instance.name,
                                                      instance))
        calls = [mock.call.container_start(instance.name, -1),
                 mock.call.wait_container_operation(
            '/1.0/operation/1234', 200, -1)]
        self.assertEqual(calls, self.ml.method_calls)

    @stubs.annotated_data(
        ('1', (200, fake_api.fake_operation_info_ok()))
    )
    def test_container_stop(self, tag, side_effect):
        """
        container_stop stops a container on a given LXD ost.
        Verifty that that the apprioated pylxd calls are
        made to the LXD api.
        """
        instance = stubs._fake_instance()
        self.ml.container_stop.return_value = side_effect
        self.assertEqual(None,
                         self.session.container_stop(instance.name,
                                                     instance))
        calls = [mock.call.container_stop(instance.name, -1),
                 mock.call.wait_container_operation(
            '/1.0/operation/1234', 200, -1)]
        self.assertEqual(calls, self.ml.method_calls)

    @stubs.annotated_data(
        ('api_fail', lxd_exceptions.APIError('Fake', 500),
         exception.NovaException)
    )
    def test_container_stop_fail(self, tag, side_effect, expected):
        """
        container_stop stops a container on a given LXD host.
        Verifty that we raise an exception.NovaException when there is an
        APIError.
        """
        instance = stubs._fake_instance()
        self.ml.container_stop.side_effect = side_effect
        self.assertRaises(expected,
                          self.session.container_stop, instance.name,
                          instance)

    @stubs.annotated_data(
        ('1,', (200, fake_api.fake_operation_info_ok()))
    )
    def test_continer_reboot(self, tag, side_effect):
        """"
        container_reboot reboots a container on a given LXD host.
        Verify that the right pylxd calls are made to the LXD host.
        """
        instance = stubs._fake_instance()
        self.ml.container_reboot.return_value = side_effect
        self.assertEqual(None,
                         self.session.container_reboot(instance))
        calls = [mock.call.container_reboot(instance.name, -1),
                 mock.call.wait_container_operation(
                     '/1.0/operation/1234', 200, -1)]
        self.assertEqual(calls, self.ml.method_calls)

    @stubs.annotated_data(
        ('api_fail', lxd_exceptions.APIError('Fake', 500),
         exception.NovaException)
    )
    def test_container_reboot_fail(self, tag, side_effect, expected):
        """
        container_reboot reboots a container on a given LXD host.
        Check that an exception.NovaException is raised when
        there is an LXD API error.
        """
        instance = stubs._fake_instance()
        self.ml.container_reboot.side_effect = side_effect
        self.assertRaises(expected,
                          self.session.container_reboot, instance)

    @stubs.annotated_data(
        ('exists', (200, fake_api.fake_operation_info_ok())),
    )
    def test_container_destroy(self, tag, side_effect):
        """
        container_destroy delete a container from the LXD Host. Check
        that the approiate pylxd calls are made.
        """
        instance = stubs._fake_instance()
        self.ml.container_stop.return_value = side_effect
        self.ml.container_destroy.return_value = side_effect
        self.assertEqual(None,
                         self.session.container_destroy(instance.name,
                                                        instance))
        calls = [mock.call.container_stop(instance.name, -1),
                 mock.call.wait_container_operation(
            '/1.0/operation/1234', 200, -1),
            mock.call.container_destroy(instance.name),
            mock.call.wait_container_operation(
            '/1.0/operation/1234', 200, -1)]
        self.assertEqual(calls, self.ml.method_calls)

    @stubs.annotated_data(
        ('fail_to_stop', True, 'fail_stop',
         lxd_exceptions.APIError('Fake', '500'), exception.NovaException),
        ('fail_to_destroy', True, 'fail_destroy',
         lxd_exceptions.APIError('Fake', '500'), exception.NovaException)
    )
    def test_container_destroy_fail(self, tag, container_defined,
                                    test_type, side_effect, expected):
        """
        container_destroy deletes a container on the LXD host.
        Check whether an exeption.NovaException is raised when
        there is an APIError or when the container fails to stop.
        """
        instance = stubs._fake_instance()
        self.ml.cotnainer_defined.return_value = container_defined
        if test_type == 'fail_stop':
            self.ml.container_stop.side_effect = side_effect
            self.assertRaises(expected,
                              self.session.container_destroy, instance.name,
                              instance)
        if test_type == 'fail_destroy':
            self.ml.container_stop.return_value = \
                (200, fake_api.fake_operation_info_ok())
            self.ml.container_destroy.side_effect = side_effect
            self.assertRaises(expected,
                              self.session.container_destroy, instance.name,
                              instance)

    @stubs.annotated_data(
        ('1', (200, fake_api.fake_operation_info_ok()))
    )
    def fake_container_pause(self, tag, side_effect):
        """
        container_pause pauses a container on a given LXD host.
        Verify that the appropiate pylxd API calls are made.
        """
        instance = stubs._fake_instance()
        self.ml.container_suspend.return_value = side_effect
        self.assertEqual(None,
                         self.session.container_pause(instance.name,
                                                      instance))
        calls = [
            mock.call.container_susepnd(instance.name, -1),
            mock.call.wait_container_operation(
                '/1.0/operation/1234', 200, -1)]
        self.assertEqual(calls, self.ml.method_calls)

    @stubs.annotated_data(
        ('api_fail', lxd_exceptions.APIError(500, 'Fake'),
         exception.NovaException)
    )
    def test_container_pause_fail(self, tag, side_effect, expected):
        """
        container_pause pauses a container on a LXD host. Verify
        that an exception.NovaException is raised when there
        is an APIError.
        """
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
        """
        container_unpase unpauses a continer on a LXD host.
        Check that the right pylxd calls are being sent
        to the LXD API server.
        """
        instance = stubs._fake_instance()
        self.ml.container_resume.return_value = side_effect
        self.assertEqual(None,
                         self.session.container_unpause(instance.name,
                                                        instance))
        calls = [
            mock.call.container_resume(instance.name, -1),
            mock.call.wait_container_operation(
                '/1.0/operation/1234', 200, -1)]
        self.assertEqual(calls, self.ml.method_calls)

    @stubs.annotated_data(
        ('api_fail', lxd_exceptions.APIError(500, 'Fake'),
         exception.NovaException)
    )
    def test_container_unpause_fail(self, tag, side_effect, expected):
        """
        container_unpause resumes a previously suespended container.
        Validate that an exception.NovaException is raised when a
        APIError is sent by the API.
        """
        instance = stubs._fake_instance()
        self.ml.container_resume.side_effect = side_effect
        self.assertRaises(expected,
                          self.session.container_unpause,
                          instance.name, instance)

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
        self.assertEqual(None,
                         self.session.container_init(config, instance))
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
            mock.call.wait_container_operation('/1.0/operation/1234', 200, -1)]
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
