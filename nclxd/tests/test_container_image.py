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

from nova import test

import ddt
import fixtures
import mock
from oslo_concurrency import lockutils
from oslo_config import fixture as config_fixture

from nclxd.nova.virt.lxd import container_client
from nclxd.nova.virt.lxd import container_image
from nclxd.nova.virt.lxd import container_utils
from nclxd.tests import stubs


@ddt.ddt
@mock.patch.object(container_image, 'CONF', stubs.MockConf())
@mock.patch.object(container_utils, 'CONF', stubs.MockConf())
class LXDTestContainerImage(test.NoDBTestCase):

    @mock.patch.object(container_utils, 'CONF', stubs.MockConf())
    def setUp(self):
        super(LXDTestContainerImage, self).setUp()

        self.tempdir = self.useFixture(fixtures.TempDir()).path
        self.fixture = self.useFixture(config_fixture.Config(lockutils.CONF))
        self.fixture.config(lock_path=self.tempdir,
                            group='oslo_concurrency')
        self.fixture.config(disable_process_locking=True,
                            group='oslo_concurrency')

        self.container_image = container_image.LXDContainerImage()
        alias_patcher = mock.patch.object(container_client.LXDContainerClient,
                                          'container_alias_defined',
                                          return_value=True)
        alias_patcher.start()
        self.addCleanup(alias_patcher.stop)

    def test_fetch_image_existing_alias(self):
        instance = stubs.MockInstance()
        context = {}
        image_meta = {'name': 'alias'}
        self.assertEqual(None,
                         self.container_image.setup_image(context,
                                                          instance,
                                                          image_meta))

    @mock.patch('os.path.exists', mock.Mock(return_value=False))
    @mock.patch('oslo_utils.fileutils.ensure_tree', mock.Mock())
    def test_fetch_image_new_defined(self):
        instance = stubs.MockInstance()
        context = {}
        image_meta = {'name': 'new_image'}
        self.assertEqual(None,
                         self.container_image.setup_image(
                             context, instance, image_meta))
