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

import ddt
import mock
from nova import exception
from nova import test
from pylxd import exceptions as lxd_exceptions

from nclxd.nova.virt.lxd import container_image
from nclxd import tests


@ddt.ddt
@mock.patch.multiple('nclxd.nova.virt.lxd.container_utils'
                     '.LXDContainerDirectories',
                     get_base_dir=mock.Mock(return_value='/fake/path'),
                     get_container_image=mock.Mock(
                         return_value='/fake/image/path'))
class LXDTestContainerImage(test.NoDBTestCase):

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
    @mock.patch('nova.openstack.common.fileutils.ensure_tree')
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
            mt.assert_called_once_with('/fake/path')
        self.assertEqual([mock.call('/fake/path'),
                          mock.call('/fake/image/path')], mo.call_args_list)

    @mock.patch('os.path.exists', mock.Mock(return_value=False))
    @mock.patch('nova.openstack.common.fileutils.ensure_tree', mock.Mock())
    @mock.patch('nova.openstack.common.fileutils.remove_path_on_error')
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
        mf.assert_called_once_with('/fake/image/path')
        mi.assert_called_once_with(
            context, 'mock_image', dest_path='/fake/image/path')

    @mock.patch('os.path.exists', mock.Mock(return_value=False))
    @mock.patch('nova.openstack.common.fileutils.ensure_tree', mock.Mock())
    @mock.patch('nova.openstack.common.fileutils.remove_path_on_error',
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
            mu.assert_called_once_with(path='/fake/image/path')
