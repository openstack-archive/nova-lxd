import os
import mock
import shutil

from oslo_config import cfg

import pylxd

from nova import test
from nova.tests.unit import fake_instance

from nclxd.nova.virt.lxd import container_utils

CONF = cfg.CONF

class LXDTestContainerDirectory(test.NoDBTestCase):
    def setUp(self):
        super(LXDTestContainerDirectory, self).setUp()
        self.container_dir = container_utils.LXDContainerDirectories()

    def test_get_base_dir(self):
        path = self.container_dir.get_base_dir()
        expected_path = os.path.join(CONF.instances_path,
                                     CONF.image_cache_subdirectory_name)
        self.assertEqual(expected_path, path)

    def test_get_container_dir(self):
        instance = fake_instance.fake_instance_obj(None, name='fake_inst',
                                                  uuid='fake_uuid')
        path = self.container_dir.get_container_dir(instance)
        expected_path = os.path.join(CONF.instances_path,
                                     instance.uuid)
        self.assertEqual(expected_path, path)

    def test_get_container_image(self):
        instance = fake_instance.fake_instance_obj(None, name='fake_inst',
                                                  uuid='fake_uuid')
        path = self.container_dir.get_container_image(instance)
        expected_path = os.path.join(CONF.instances_path,
                                      CONF.image_cache_subdirectory_name,
                                      '%s.tar.gz' % instance.image_ref)
        self.assertEqual(expected_path, path)

    def test_get_container_configdrive(self):
        instance = fake_instance.fake_instance_obj(None, name='fake_inst',
                                                  uuid='fake_uuid')
        path = self.container_dir.get_container_configdirve(instance)
        expected_path = os.path.join(CONF.instances_path,
                                     instance.uuid,
                                     'config-drive')
        self.assertEqual(expected_path, path)

    def test_get_console_path(self):
        instance = fake_instance.fake_instance_obj(None, name='fake_inst',
                                                  uuid='fake_uuid')
        path = self.container_dir.get_console_path(instance)
        expected_path = os.path.join(CONF.lxd.lxd_root_dir,
                                     'lxc',
                                      instance.uuid,
                                      'console.log')
        self.assertEqual(expected_path, path)

    def test_get_container_dir(self):
        instance = fake_instance.fake_instance_obj(None, name='fake_inst',
                                                  uuid='fake_uuid')
        path = self.container_dir.get_container_dir(instance)
        expected_path = os.path.join(CONF.lxd.lxd_root_dir,
                                     'lxc',
                                     instance.uuid)
        self.assertEqual(expected_path, path)

    def test_get_container_rootfs(self):
        instance = fake_instance.fake_instance_obj(None, name='fake_inst',
                                                  uuid='fake_uuid')
        path = self.container_dir.get_container_rootfs(instance)
        expected_path = os.path.join(CONF.lxd.lxd_root_dir,
                                     'lxc',
                                     instance.uuid,
                                     'rootfs')
        self.assertEqual(expected_path, path)

class LXDTestContainerUtils(test.NoDBTestCase):
    def setUp(self):
        super(LXDTestContainerUtils, self).setUp()
        self.container_utils = container_utils.LXDContainerUtils()

    @mock.patch.object(pylxd.api.API, 'host_ping')
    def test_init_lxd_host(self, mock_ping):
        mock_ping.return_value = True
        self.assertTrue(self.container_utils.init_lxd_host("fakehost"))

    @mock.patch.object(pylxd.api.API, 'container_list')
    def test_container_list(self, mock_container_list):
        mock_container_list.return_value = ['instance-0001',
                                           'instance-0002']
        self.assertEqual(len(self.container_utils.list_containers()), 2)

    @mock.patch.object(pylxd.api.API, 'container_start')
    def test_container_start(self, mock_container_start):
        mock_container_start.return_value = True
        instance = fake_instance.fake_instance_obj(None, name='fake_inst',
                                                  uuid='fake_uuid')
        self.assertTrue(self.container_utils.container_start(instance))

    @mock.patch.object(pylxd.api.API, 'container_destroy')
    def test_container_destroy(self, mock_container_destroy):
        mock_container_destroy.return_value = True
        instance = fake_instance.fake_instance_obj(None, name='fake_inst',
                                                  uuid='fake_uuid')
        self.assertTrue(self.container_utils.container_destroy(instance))

