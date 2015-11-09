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

import mock

from nova import exception
from nova import test

from nova_lxd.nova.virt.lxd import container_client
from nova_lxd.nova.virt.lxd import container_utils
from nova_lxd.tests import fake_api
from nova_lxd.tests import stubs


@mock.patch.object(container_utils, 'CONF', stubs.MockConf())
class LXDTestContainerUtils(test.NoDBTestCase):

    @mock.patch.object(container_utils, 'CONF', stubs.MockConf())
    def setUp(self):
        super(LXDTestContainerUtils, self).setUp()

        self.container_utils = container_utils.LXDContainerUtils()

    def test_container_start(self):
        instance = stubs._fake_instance()
        instance_name = 'fake-uuid'
        with contextlib.nested(
            mock.patch.object(container_client.LXDContainerClient,
                              'container_start'),
            mock.patch.object(container_client.LXDContainerClient,
                              'container_wait'),
        ) as (
            container_start,
            container_wait
        ):
            container_start.return_value = (200, fake_api.fake_operation())
            self.assertEqual(None,
                             (self.container_utils.container_start(
                                 instance_name, instance)))
            self.assertTrue(container_start)
            self.assertTrue(container_wait)

    def test_container_stop(self):
        instance = stubs._fake_instance()
        instance_name = 'fake-uuid'
        with contextlib.nested(
            mock.patch.object(container_client.LXDContainerClient,
                              'container_stop'),
            mock.patch.object(container_client.LXDContainerClient,
                              'container_wait'),
        ) as (
            container_stop,
            container_wait
        ):
            container_stop.return_value = (200, fake_api.fake_operation())
            self.assertEqual(None,
                             (self.container_utils.container_stop(
                                 instance_name, instance)))
            self.assertTrue(container_stop)
            self.assertTrue(container_wait)

    def test_container_reboot(self):
        instance = stubs._fake_instance()
        with contextlib.nested(
            mock.patch.object(container_client.LXDContainerClient,
                              'container_reboot'),
            mock.patch.object(container_client.LXDContainerClient,
                              'container_wait'),
        ) as (
            container_reboot,
            container_wait
        ):
            container_reboot.return_value = (200, fake_api.fake_operation())
            self.assertEqual(None,
                             self.container_utils.container_reboot(instance))
            self.assertTrue(container_reboot)
            self.assertTrue(container_wait)

    def test_container_destroy(self):
        instance_name = mock.Mock()
        host = mock.Mock()
        with contextlib.nested(
            mock.patch.object(container_client.LXDContainerClient,
                              'container_defined'),
            mock.patch.object(container_utils.LXDContainerUtils,
                              'container_stop'),
            mock.patch.object(container_client.LXDContainerClient,
                              'container_destroy'),
            mock.patch.object(container_client.LXDContainerClient,
                              'container_wait')
        ) as (
            container_defined,
            container_stop,
            container_destroy,
            container_wait
        ):
            container_defined.retrun_value = True
            container_destroy.return_value = (200, fake_api.fake_operation())
            self.assertEqual(None,
                             (self.container_utils.container_destroy(
                                 instance_name, host)))
            self.assertTrue(container_defined)
            self.assertTrue(container_stop)
            self.assertTrue(container_destroy)
            self.assertTrue(container_wait)

    def test_container_pause(self):
        instance = stubs._fake_instance()
        instance_name = 'fake-uuid'
        with contextlib.nested(
            mock.patch.object(container_client.LXDContainerClient,
                              'container_pause'),
            mock.patch.object(container_client.LXDContainerClient,
                              'container_wait'),
        ) as (
            container_pause,
            container_wait
        ):
            container_pause.return_value = (200, fake_api.fake_operation())
            self.assertEqual(None,
                             (self.container_utils.container_pause(
                                 instance_name, instance)))
            self.assertTrue(container_pause)
            self.assertTrue(container_wait)

    def test_container_unpause(self):
        instance = stubs._fake_instance()
        instance_name = 'fake-uuid'
        with contextlib.nested(
            mock.patch.object(container_client.LXDContainerClient,
                              'container_pause'),
            mock.patch.object(container_client.LXDContainerClient,
                              'container_wait'),
        ) as (
            container_pause,
            container_wait
        ):
            container_pause.return_value = (200, fake_api.fake_operation())
            self.assertEqual(None,
                             self.container_utils.container_pause(
                                 instance_name, instance))
            self.assertTrue(container_pause)
            self.assertTrue(container_wait)

    def test_container_suspend(self):
        instance = stubs._fake_instance()
        snapshot = mock.Mock()
        with contextlib.nested(
            mock.patch.object(container_client.LXDContainerClient,
                              'container_snapshot_create'),
            mock.patch.object(container_client.LXDContainerClient,
                              'container_wait'),
        ) as (
            snapshot_create,
            container_wait
        ):
            snapshot_create.return_value = (200, fake_api.fake_operation())
            self.assertEqual(None,
                             (self.container_utils.container_snapshot(
                                 snapshot, instance)))
            self.assertTrue(snapshot_create)
            self.assertTrue(container_wait)

    def test_container_copy(self):
        instance = stubs._fake_instance()
        config = mock.Mock()

        with contextlib.nested(
            mock.patch.object(container_client.LXDContainerClient,
                              'container_local_copy'),
            mock.patch.object(container_client.LXDContainerClient,
                              'container_wait'),
        ) as (
            container_copy,
            container_wait
        ):
            container_copy.return_value = (200, fake_api.fake_operation())
            self.assertEqual(None,
                             (self.container_utils.container_copy(config,
                                                                  instance)))
            self.assertTrue(container_copy)
            self.assertTrue(container_wait)

    def test_container_move(self):
        instance = stubs._fake_instance()
        config = mock.Mock()
        old_name = mock.Mock()

        with contextlib.nested(
            mock.patch.object(container_client.LXDContainerClient,
                              'container_local_move'),
            mock.patch.object(container_client.LXDContainerClient,
                              'container_wait'),
        ) as (
            container_move,
            container_wait
        ):
            container_move.return_value = (200, fake_api.fake_operation())
            self.assertEqual(None,
                             (self.container_utils.container_move(old_name,
                                                                  config,
                                                                  instance)))
            self.assertTrue(container_move)
            self.assertTrue(container_wait)

    def test_container_init(self):
        config = mock.Mock()
        instance = stubs._fake_instance()
        host = mock.Mock()
        with contextlib.nested(
            mock.patch.object(container_client.LXDContainerClient,
                              'container_init'),
            mock.patch.object(container_client.LXDContainerClient,
                              'container_wait'),
            mock.patch.object(container_client.LXDContainerClient,
                              'container_operation_info'),
        ) as (
            container_init,
            container_wait,
            container_operation_info,
        ):
            container_init.return_value = (200, fake_api.fake_operation())
            container_operation_info.return_value = (
                200,
                fake_api.fake_operation_info_ok())
            self.assertEqual(None,
                             (self.container_utils.container_init(config,
                                                                  instance,
                                                                  host)))
            self.assertTrue(container_init)
            self.assertTrue(container_wait)
            self.assertTrue(container_operation_info)

    def test_container_init_failure(self):
        config = mock.Mock()
        instance = stubs._fake_instance()
        host = mock.Mock()
        with contextlib.nested(
            mock.patch.object(container_client.LXDContainerClient,
                              'container_init'),
            mock.patch.object(container_client.LXDContainerClient,
                              'container_wait'),
            mock.patch.object(container_client.LXDContainerClient,
                              'container_operation_info'),
        ) as (
            container_init,
            container_wait,
            container_operation_info,
        ):
            container_init.return_value = (200, fake_api.fake_operation())
            container_operation_info.return_value = (
                200,
                fake_api.fake_operation_info_failed())
            self.assertRaises(exception.NovaException,
                              self.container_utils.container_init,
                              config, instance, host)
            self.assertTrue(container_init)
            self.assertTrue(container_wait)
            self.assertTrue(container_operation_info)
