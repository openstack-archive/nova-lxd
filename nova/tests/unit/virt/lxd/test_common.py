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

from nova import context
from nova import test
from nova.tests.unit import fake_instance

from nova.virt.lxd import common


class InstanceAttributesTest(test.NoDBTestCase):
    """Tests for InstanceAttributes."""

    def setUp(self):
        super(InstanceAttributesTest, self).setUp()

        self.CONF_patcher = mock.patch('nova.virt.lxd.driver.nova.conf.CONF')
        self.CONF = self.CONF_patcher.start()
        self.CONF.instances_path = '/i'
        self.CONF.lxd.root_dir = '/c'

    def tearDown(self):
        super(InstanceAttributesTest, self).tearDown()
        self.CONF_patcher.stop()

    def test_is_snap_lxd(self):
        with mock.patch('os.path.isfile') as isfile:
            isfile.return_value = False
            self.assertFalse(common.is_snap_lxd())
            isfile.return_value = True
            self.assertTrue(common.is_snap_lxd())

    @mock.patch.object(common, 'is_snap_lxd')
    def test_instance_dir(self, is_snap_lxd):
        ctx = context.get_admin_context()
        instance = fake_instance.fake_instance_obj(
            ctx, name='test', memory_mb=0)
        is_snap_lxd.return_value = False

        attributes = common.InstanceAttributes(instance)

        self.assertEqual(
            '/i/instance-00000001', attributes.instance_dir)

    @mock.patch.object(common, 'is_snap_lxd')
    def test_console_path(self, is_snap_lxd):
        ctx = context.get_admin_context()
        instance = fake_instance.fake_instance_obj(
            ctx, name='test', memory_mb=0)
        is_snap_lxd.return_value = False

        attributes = common.InstanceAttributes(instance)
        self.assertEqual(
            '/var/log/lxd/instance-00000001/console.log',
            attributes.console_path)

        is_snap_lxd.return_value = True
        attributes = common.InstanceAttributes(instance)
        self.assertEqual(
            '/var/snap/lxd/common/lxd/logs/instance-00000001/console.log',
            attributes.console_path)

    @mock.patch.object(common, 'is_snap_lxd')
    def test_storage_path(self, is_snap_lxd):
        ctx = context.get_admin_context()
        instance = fake_instance.fake_instance_obj(
            ctx, name='test', memory_mb=0)
        is_snap_lxd.return_value = False

        attributes = common.InstanceAttributes(instance)

        self.assertEqual(
            '/i/instance-00000001/storage',
            attributes.storage_path)
