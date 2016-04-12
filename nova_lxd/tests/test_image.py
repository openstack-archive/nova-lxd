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

import io
import json
from nova import exception
from nova import test
import os
import tarfile

import ddt
import fixtures
import mock
from oslo_concurrency import lockutils
from oslo_config import fixture as config_fixture


from nova_lxd.nova.virt.lxd import image
from nova_lxd.nova.virt.lxd import session
from nova_lxd.tests import stubs


@ddt.ddt
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

    @stubs.annotated_data(
        ('valid_image_raw', True, {'disk_format': 'raw'}, None),
        ('valid_image_root-tar', True, {'disk_format': 'root-tar'}, None),
        ('qcow2_image', False, {'disk_format': 'qcow2'},
            exception.ImageUnacceptable),
        ('iso_image', False, {'disk_format': 'iso'},
            exception.ImageUnacceptable),
        ('image_unacceptable', False, {'disk_format': ''},
            exception.ImageUnacceptable),
        ('bad_meta', False, {},
            exception.ImageUnacceptable),
    )
    def test_image(self, tag, sucess, image_data, expected):
        context = mock.Mock
        instance = stubs._fake_instance()
        with mock.patch.object(image.IMAGE_API, 'get',
                               return_value=image_data):
            if sucess:
                self.assertEqual(expected,
                                 self.image._verify_image(context, instance))
            else:
                self.assertRaises(expected,
                                  self.image._verify_image, context, instance)

    @mock.patch.object(image.IMAGE_API, 'download')
    def test_fetch_image(self, mock_download):
        context = mock.Mock()
        instance = stubs._fake_instance()
        self.assertEqual(None,
                         self.image._fetch_image(context, instance))

    @mock.patch.object(os, 'stat')
    @mock.patch.object(json, 'dumps')
    @mock.patch.object(tarfile, 'open')
    @mock.patch.object(io, 'BytesIO')
    @mock.patch.object(image.IMAGE_API, 'get')
    def test_get_lxd_manifest(self, mock_stat, mock_json, mock_tarfile,
                              mock_io, mock_image):
        instance = stubs._fake_instance()
        image_meta = mock.Mock()
        self.assertEqual(None,
                         self.image._get_lxd_manifest(instance, image_meta))
