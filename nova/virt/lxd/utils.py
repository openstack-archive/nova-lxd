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

import nova.conf

CONF = nova.conf.CONF
BASE_DIR = os.path.join(
    CONF.instances_path, CONF.image_cache_subdirectory_name)


def get_instance_dir(instance):
    return os.path.join(CONF.instances_path, instance)


def get_container_rootfs_image(image_meta):
    return os.path.join(BASE_DIR, '%s-rootfs.tar.gz' % image_meta.id)


def get_container_manifest_image(image_meta):
    return os.path.join(BASE_DIR, '%s-manifest.tar.gz' % image_meta.id)


def get_container_storage(ephemeral, instance):
    return os.path.join(CONF.instances_path, instance, 'storage', ephemeral)


def get_console_path(instance):
    return os.path.join('/var/log/lxd/', instance, 'console.log')


def get_container_dir(instance):
    return os.path.join(CONF.lxd.root_dir, 'containers')


def get_container_rootfs(instance):
    return os.path.join(CONF.lxd.root_dir, 'containers', instance, 'rootfs')


def get_container_rescue(instance):
    return os.path.join(CONF.lxd.root_dir, 'containers', instance, 'rootfs')


def get_container_configdrive(instance):
    return os.path.join(CONF.instances_path, instance, 'configdrive')
