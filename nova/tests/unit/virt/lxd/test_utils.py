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


import fixtures
import os

from nova import objects
from nova import test
from nova.tests.unit import fake_instance

from nova.virt.lxd import utils


class LXDTestContainerUtils(test.NoDBTestCase):
    """LXD Container utilities unit tests."""

    def setUp(self):
        super(LXDTestContainerUtils, self).setUp()

        self.context = 'fake-context'
        self.temp_dir = self.useFixture(fixtures.TempDir()).path
        self.flags(instances_path=self.temp_dir)

        self.utils = utils.LXDContainerDirectories()
        self.base_dir = os.path.join(self.temp_dir, '_base')

    def test_get_base_dir(self):
        """Verify the base directory that holds the images is correct."""
        self.assertEqual(self.base_dir,
                         self.utils.get_base_dir())

    def test_instance_dir(self):
        """Verify the image rootfs file is correct."""
        mock_instance = fake_instance.fake_instance_obj(self.context)
        self.assertEqual(os.path.join(self.temp_dir, mock_instance.name),
                         self.utils.get_instance_dir(mock_instance.name))

    def test_container_rootfs_img(self):
        """Verify the image rootfs file is correct."""
        image_meta = objects.ImageMeta.from_dict({"id": 'fake_id'})
        self.assertEqual(os.path.join(self.base_dir, 'fake_id-rootfs.tar.gz'),
                         self.utils.get_container_rootfs_image(image_meta))

    def test_container_manifest(self):
        """Verify the image metadata file is correct."""
        image_meta = objects.ImageMeta.from_dict({"id": 'fake_id'})
        self.assertEqual(os.path.join(self.base_dir, 'fake_id-manifest.tar'),
                         self.utils.get_container_manifest_image(image_meta))

    def test_container_configdrive(self):
        """Verify the container config drive path is correct."""
        mock_instance = fake_instance.fake_instance_obj(self.context)
        self.assertEqual(os.path.join(
            self.temp_dir, mock_instance.name, 'configdrive'),
            self.utils.get_container_configdrive(mock_instance.name))

    def test_container_console_log(self):
        """Verify the container console log path is correct."""
        mock_instance = fake_instance.fake_instance_obj(self.context)
        self.assertEqual(os.path.join(
            '/var/log/lxd', mock_instance.name, 'console.log'),
            self.utils.get_console_path(mock_instance.name))

    def test_container_dir(self):
        """Verify the container dir is correct."""
        mock_instance = fake_instance.fake_instance_obj(self.context)
        self.assertEqual(os.path.join(
            '/var/lib/lxd', 'containers'),
            self.utils.get_container_dir(mock_instance.name))

    def test_container_rescue(self):
        """Verify the rescue container path is correct."""
        mock_instance = fake_instance.fake_instance_obj(self.context)
        self.assertEqual(os.path.join(
            '/var/lib/lxd', 'containers', mock_instance.name, 'rootfs'),
            self.utils.get_container_rescue(mock_instance.name))