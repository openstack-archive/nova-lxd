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

import os

from oslo_config import cfg

CONF = cfg.CONF


class LXDContainerDirectories(object):

    def __init__(self):
        self.base_dir = os.path.join(CONF.instances_path,
                                     CONF.image_cache_subdirectory_name)

    def get_base_dir(self):
        return self.base_dir

    def get_instance_dir(self, instance):
        return os.path.join(CONF.instances_path,
                            instance)

    def get_container_rootfs_image(self, image_meta):
        return os.path.join(self.base_dir,
                            '%s-rootfs.tar.gz' % image_meta.id)

    def get_container_manifest_image(self, image_meta):
        return os.path.join(self.base_dir,
                            '%s-manifest.tar' % image_meta.id)

    def get_container_metadata(self, image_meta):
        return os.path.join(self.base_dir,
                            '%s-lxd.tar.xz' % image_meta.id)

    def get_container_rootfsImg(self, image_meta):
        return os.path.join(self.base_dir,
                            '%s-root.tar.gz' % image_meta.id)

    def get_container_configdrive(self, instance):
        return os.path.join(CONF.instances_path,
                            instance,
                            'configdrive')

    def get_console_path(self, instance):
        return os.path.join('/var/log/lxd/',
                            instance,
                            'console.log')

    def get_container_dir(self, instance):
        return os.path.join(CONF.lxd.root_dir,
                            'containers')

    def get_container_rootfs(self, instance):
        return os.path.join(CONF.lxd.root_dir,
                            'containers',
                            instance,
                            'rootfs')

    def get_container_rescue(self, instance):
        if self.is_lvm(instance):
            return os.path.join(CONF.lxd.root_dir,
                                'containers',
                                instance)
        else:
            return os.path.join(CONF.lxd.root_dir,
                                'containers',
                                instance,
                                'rootfs')

    def get_container_lvm(self, instance):
        return '%s/%s.lv' % (self.get_container_dir(instance),
                             instance)

    def is_lvm(self, instance):
        try:
            if os.path.exists(os.readlink(
                self.get_container_lvm(instance))):
                return True
        except Exception:
            return False
