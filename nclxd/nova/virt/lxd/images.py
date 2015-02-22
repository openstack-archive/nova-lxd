# Copyright (c) 2015 Canonical Ltd
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

import tarfile

from oslo.config import cfg
from oslo.utils import units, excutils


from nova import utils
from nova.i18n import _, _LI
from nova.openstack.common import fileutils
from nova.openstack.common import log as logging
from nova.virt import images
from nova import exception

from . import utils as container_utils

CONF = cfg.CONF
LOG = logging.getLogger(__name__)


class ContainerImage(object):
    def __init__(self, context, instance, image_meta):
        self.context = context
        self.image_meta = image_meta
        self.instance = instance
        self.max_size = 0

        self.base_dir = os.path.join(CONF.lxd.lxd_root_dir,
                                     CONF.image_cache_subdirectory_name)
        self.root_dir = os.path.join(CONF.lxd.lxd_root_dir,
                                     self.instance['uuid'])
        self.container_dir = os.path.join(self.root_dir, 'rootfs')
        self.image_dir = os.path.join(self.base_dir,
                                      self.instance['image_ref'])
        self.container_image = os.path.join(self.base_dir,
                                            '%s.tar.gz' % self.instance['image_ref'])
        self.container_console = os.path.join(self.root_dir, 'container.console')

        if not os.path.exists(self.base_dir):
            fileutils.ensure_tree(self.base_dir)

        (out, err) = utils.execute('stat', '-f', '-c', '%T', self.base_dir)
        self.filesystem_type = out.rstrip()

    def create_container(self):
        LOG.info(_LI('Fetching image from glance.'))

        disk_format = self.image_meta.get('disk_format')
        if disk_format != 'root-tar' and disk_format is not None:
            msg = _('Unable to determine disk format for image.')
            raise exception.Invalid(msg)

        if not os.path.exists(self.root_dir):
            fileutils.ensure_tree(self.root_dir)

        if not os.path.exists(self.container_image):
            try:
                images.fetch_to_raw(self.context, self.instance['image_ref'], self.container_image,
                                    self.instance['user_id'], self.instance['project_id'],
                                    max_size=self.max_size)
            except Exception as ex:
                    with excutils.save_and_reraise_exception():
                            os.unlink(self.container_image)
                            msg = _('Failed to download image.')
                            raise exception.Invalid(msg)


            if not tarfile.is_tarfile(self.container_image):
                msg = _('Not a valid tarfile')
                raise exception.InvalidImageRef(msg)

        if os.path.exists(self.container_dir):
            msg = _('Container rootfs already exists')
            raise exception.NovaException(msg)

        if self.filesystem_type == 'btrfs':
            self.create_btrfs_container()
        else:
            self.create_local_container()

    def create_btrfs_container(self):
        LOG.info(_LI('Creating btrfs container rootfs'))

        if not os.path.exists(self.image_dir):
            utils.execute('btrfs', 'subvolume', 'create', self.image_dir)
            self._write_image(self.image_dir)
        
        size = self.instance['root_gb']
        utils.execute('btrfs', 'subvolume', 'snapshot', self.image_dir,
                      self.container_dir, run_as_root=True)
        if size != 0:
            utils.execute('btrfs', 'quota', 'enable', self.container_dir,
                         run_as_root=True)
            utils.execute('btrfs', 'qgroup', 'limit', '%sG' % size,
                          self.container_dir, run_as_root=True)


    def create_local_container(self):
        LOG.info(_LI('Creating local container rootfs'))

        if not os.path.exists(self.container_dir):
            fileutils.ensure_tree(self.container_dir)
        utils.execute('touch', self.container_console)
        self._write_image(self.container_dir)

    def _write_image(self, image_dir):
        (user, cgroup) = container_utils.parse_subfile(CONF.lxd.lxd_default_user,
                                                      '/etc/subuid')
        (group, cgroup) = container_utils.parse_subfile(CONF.lxd.lxd_default_user,
                                                        '/etc/subgid')
        utils.execute('tar', '--directory', image_dir,
                      '--anchored', '--numeric-owner',
                      '-xpzf', self.container_image,
                      check_exit_code=[0,2])
        utils.execute('chown', '-R', '%s:%s' % (user, group),
                      image_dir,
                      run_as_root=True)