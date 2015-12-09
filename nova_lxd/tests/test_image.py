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
import os

import ddt
import fixtures
import mock
from oslo_concurrency import lockutils
from oslo_config import fixture as config_fixture


from nova_lxd.nova.virt.lxd import image
from nova_lxd.nova.virt.lxd.session import session
from nova_lxd.tests import stubs


@ddt.ddt
@mock.patch.object(image, 'CONF', stubs.MockConf())
@mock.patch.object(session, 'CONF', stubs.MockConf())
class LXDTestContainerImage(test.NoDBTestCase):

    @mock.patch.object(session, 'CONF', stubs.MockConf())
    def setUp(self):
        super(LXDTestContainerImage, self).setUp()

        self.tempdir = self.useFixture(fixtures.TempDir()).path
        self.fixture = self.useFixture(config_fixture.Config(lockutils.CONF))
        self.fixture.config(lock_path=self.tempdir,
                            group='oslo_concurrency')
        self.fixture.config(disable_process_locking=True,
                            group='oslo_concurrency')

        self.image = image.LXDContainerImage()

    @mock.patch('os.path.exists', mock.Mock(return_value=False))
    @mock.patch('oslo_utils.fileutils.ensure_tree', mock.Mock())
    @mock.patch('nova.utils.execute')
    def test_fetch_image(self, mock_execute):
        context = mock.Mock()
        instance = stubs._fake_instance()
        image_meta = {'name': 'new_image', 'id': 'fake_image'}
        with test.nested(
                mock.patch.object(session.LXDAPISession,
                                  'image_defined'),
                mock.patch.object(image.IMAGE_API,
                                  'download'),
                mock.patch.object(image.LXDContainerImage,
                                  '_get_lxd_manifest'),
                mock.patch.object(image.LXDContainerImage,
                                  '_image_upload'),
                mock.patch.object(image.LXDContainerImage,
                                  '_setup_alias'),
                mock.patch.object(os, 'unlink')
        ) as (
                mock_image_defined,
                mock_image_download,
                mock_image_manifest,
                image_upload,
                setup_alias,
                os_unlink
        ):
            mock_image_defined.return_value = False
            mock_image_manifest.return_value = \
                '/fake/image/cache/fake_image-manifest.tar'
            self.assertEqual(None,
                             self.image.setup_image(context,
                                                    instance,
                                                    image_meta))
            mock_execute.assert_called_once_with('xz', '-9',
                                                 '/fake/image/cache/'
                                                 'fake_image-manifest.tar')

    @mock.patch('os.path.exists', mock.Mock(return_value=False))
    @mock.patch('oslo_utils.fileutils.ensure_tree', mock.Mock())
    @mock.patch('nova.utils.execute')
    def test_fetch_imagei_fail(self, mock_execute):
        context = mock.Mock()
        instance = stubs._fake_instance()
        image_meta = {'name': 'new_image', 'id': 'fake_image'}
        with test.nested(
            mock.patch.object(session.LXDAPISession,
                              'image_defined'),
            mock.patch.object(image.IMAGE_API,
                              'download'),
            mock.patch.object(image.LXDContainerImage,
                              '_get_lxd_manifest'),
            mock.patch.object(image.LXDContainerImage,
                              '_image_upload'),
            mock.patch.object(image.LXDContainerImage,
                              '_setup_alias'),
            mock.patch.object(os, 'unlink')
        ) as (
            mock_image_defined,
            mock_image_download,
            mock_image_manifest,
            image_upload,
            setup_alias,
            os_unlink
        ):
            mock_image_defined.return_value = True
            self.assertEqual(None,
                             self.image.setup_image(context,
                                                    instance,
                                                    image_meta))
            self.assertFalse(mock_image_manifest.called)
