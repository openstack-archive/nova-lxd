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

from nova import exception
from nova import test
from pylxd import exceptions as lxd_exceptions

import ddt
import mock

from nclxd.nova.virt.lxd import container_image
from nclxd.nova.virt.lxd import container_utils
from nclxd import tests


@ddt.ddt
@mock.patch.object(container_image, 'CONF', tests.MockConf())
@mock.patch.object(container_utils, 'CONF', tests.MockConf())
class LXDTestContainerImage(test.NoDBTestCase):

    @mock.patch.object(container_utils, 'CONF', tests.MockConf())
    def setUp(self):
        super(LXDTestContainerImage, self).setUp()
        self.container_image = container_image.LXDContainerImage()
        alias_patcher = mock.patch.object(self.container_image.lxd,
                                          'alias_list',
                                          return_value=['alias'])
        alias_patcher.start()
        self.addCleanup(alias_patcher.stop)

    def test_fetch_image_existing_alias(self):
        instance = tests.MockInstance()
        context = {}
        image_meta = {'name': 'alias'}
        self.assertEqual(None,
                         self.container_image.fetch_image(context,
                                                          instance,
                                                          image_meta))

    @mock.patch('os.path.exists')
    @mock.patch('oslo_utils.fileutils.ensure_tree')
    @ddt.data(True, False)
    def test_fetch_image_existing_file(self, base_exists, mt, mo):
        mo.side_effect = [base_exists, True]
        instance = tests.MockInstance()
        context = {}
        image_meta = {'name': 'new_image'}
        self.assertEqual(None,
                         self.container_image.fetch_image(context,
                                                          instance,
                                                          image_meta))
        if base_exists:
            self.assertFalse(mt.called)
        else:
            mt.assert_called_once_with('/fake/image/cache')
        self.assertEqual([mock.call('/fake/image/cache'),
                          mock.call('/fake/image/cache/new_image.tar.gz')],
                         mo.call_args_list)

    @mock.patch('os.path.exists', mock.Mock(return_value=False))
    @mock.patch('oslo_utils.fileutils.ensure_tree', mock.Mock())
    @mock.patch('oslo_utils.fileutils.remove_path_on_error')
    def test_fetch_image_new_defined(self, mf):
        instance = tests.MockInstance()
        context = {}
        image_meta = {'name': 'new_image'}
        with (
                mock.patch.object(container_image.IMAGE_API,
                                  'download')) as mi, (
                mock.patch.object(self.container_image.lxd,
                                  'image_defined', return_value=True)) as ml:
            self.assertRaises(exception.ImageUnacceptable,
                              self.container_image.fetch_image,
                              context, instance, image_meta)
            ml.assert_called_once_with('mock_image')
        mf.assert_called_once_with('/fake/image/cache/new_image.tar.gz')
        mi.assert_called_once_with(
            context, 'mock_image',
            dest_path='/fake/image/cache/new_image.tar.gz')

    @mock.patch('os.path.exists', mock.Mock(return_value=False))
    @mock.patch('oslo_utils.fileutils.ensure_tree', mock.Mock())
    @mock.patch('oslo_utils.fileutils.remove_path_on_error',
                mock.MagicMock())
    def test_fetch_image_new_upload_failed(self):
        instance = tests.MockInstance()
        context = {}
        image_meta = {'name': 'new_image'}
        with (
                mock.patch.object(container_image.IMAGE_API,
                                  'download')), (
                mock.patch.object(self.container_image.lxd,
                                  'image_defined', return_value=False)), (
                mock.patch.object(self.container_image.lxd,
                                  'image_upload',
                                  side_effect=lxd_exceptions.APIError(
                                      'Fake error', 500))) as mu:
            self.assertRaises(exception.ImageUnacceptable,
                              self.container_image.fetch_image,
                              context, instance, image_meta)
            mu.assert_called_once_with(
                path='/fake/image/cache/new_image.tar.gz')

    @mock.patch('os.path.exists', mock.Mock(return_value=False))
    @mock.patch('oslo_utils.fileutils.ensure_tree', mock.Mock())
    @mock.patch('oslo_utils.fileutils.remove_path_on_error',
                mock.MagicMock())
    def test_fetch_image_new_alias_failed(self):
        instance = tests.MockInstance()
        context = {}
        image_meta = {'name': 'new_image'}
        with (
                mock.patch.object(container_image.IMAGE_API,
                                  'download')), (
                mock.patch.object(self.container_image.lxd,
                                  'image_defined', return_value=False)), (
                mock.patch.object(self.container_image.lxd,
                                  'image_upload')), (
                mock.patch.object(self.container_image.lxd,
                                  'alias_create',
                                  side_effect=lxd_exceptions.APIError(
                                      'Fake error', 500))), (
                mock.patch('six.moves.builtins.open')) as mo:
            mo.return_value.__enter__.return_value.read.return_value = b'image'
            self.assertRaises(exception.ImageUnacceptable,
                              self.container_image.fetch_image,
                              context, instance, image_meta)

    @mock.patch('os.path.exists', mock.Mock(return_value=False))
    @mock.patch('oslo_utils.fileutils.ensure_tree', mock.Mock())
    @mock.patch('oslo_utils.fileutils.remove_path_on_error',
                mock.MagicMock())
    def test_fetch_image_new(self):
        instance = tests.MockInstance()
        context = {}
        image_meta = {'name': 'new_image'}
        with (
                mock.patch.object(container_image.IMAGE_API,
                                  'download')), (
                mock.patch.object(self.container_image.lxd,
                                  'image_defined', return_value=False)), (
                mock.patch.object(self.container_image.lxd,
                                  'image_upload')), (
                mock.patch.object(self.container_image.lxd,
                                  'alias_create')) as ma, (
                mock.patch('six.moves.builtins.open')) as mo:
            mo.return_value.__enter__.return_value.read.return_value = b'image'
            self.assertEqual(None,
                             self.container_image.fetch_image(context,
                                                              instance,
                                                              image_meta))
            ma.assert_called_with(
                {'name': 'new_image',
                 'target': '6105d6cc76af400325e94d588ce511be'
                 '5bfdbb73b437dc51eca43917d7a43e3d'})
