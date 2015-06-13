#    Copyright 2015 Canonical Ltd
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
import os
from oslo_config import cfg

from nova import test
from nova.tests.unit import fake_instance
from nclxd.nova.virt.lxd import container_utils

CONF = cfg.CONF

class LXDUitlsTestCase(test.NoDBTestCase):
    def test_get_base_dir(self):
        path = container_utils.get_base_dir()
        expected_path = os.path.join(CONF.instances_path,
                                    CONF.image_cache_subdirectory_name)
        self.assertEqual(expected_path, path)

    def test_get_container_image(self):
        instance = fake_instance.fake_instance_obj(None, name='fake_inst',
                                                  uuid='fake_uuid')
        path = container_utils.get_container_image(instance)
        expected_path = os.path.join(CONF.instances_path,
                                     CONF.image_cache_subdirectory_name,
                                     '%s.tar.gz' % instance.image_ref)
        self.assertEqual(expected_path, path)

    def test_get_console_path(self):
        instance = fake_instance.fake_instance_obj(None, name='fake_inst',
                                                   uuid='fake_uuid')
        path = container_utils.get_console_path(instance)
        expected_path = os.path.join(CONF.lxd.lxd_root_dir,
                                     'lxc',
                                     instance.uuid,
                                     'console.log')
        self.assertEqual(expected_path, path)

    def test_get_container_dir(self):
        instance = fake_instance.fake_instance_obj(None, name='fake_inst',
                                                    uuid='fake_uuid')
        path = container_utils.get_container_dir(instance)
        expected_path = os.path.join(CONF.lxd.lxd_root_dir,
                                     'lxc',
                                     instance.uuid)
        self.assertEqual(expected_path, path)

    @mock.patch('nova.virt.images.fetch')
    def test_fetch_image(self, mock_images):
        instance = fake_instance.fake_instance_obj(None, name='fake_inst',
                                                   uuid='fake_uuid')
        context = 'opaque context'
        target = '/tmp/targetfile'

        container_utils.fetch_image(context, target, instance)

        mock_images.assert_called_once_with(context, None, target,
                                            instance.user_id, instance.project_id,
                                            max_size=0)
