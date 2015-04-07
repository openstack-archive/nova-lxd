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


from oslo.config import cfg
from oslo_log import log as logging
from oslo_utils import excutils

from nova.i18n import _, _LE
from nova.openstack.common import fileutils
from nova import utils
from nova.virt import images
from nova import exception

CONF = cfg.CONF
LOG = logging.getLogger(__name__)


class ContainerImage(object):

    def __init__(self, client, idmap):
        self.client = client
        self.metadata = {}
        self.idmap = idmap

        self.image_dir = None
        self.rootfs_dir = None
        self.upper_dir = None
        self.work_dir = None

        self.base_dir = os.path.join(CONF.instances_path,
                                     CONF.image_cache_subdirectory_name)

    def fetch_image(self, context, instance, image_meta):
        LOG.debug(_('Fetching image from glance'))

        container_image = os.path.join(self.base_dir,
                                       '%s.tar.gz' % instance.image_ref)
        if not os.path.exists(container_image):
            fileutils.ensure_tree(self.base_dir)

        self.image_dir = os.path.join(CONF.instances_path,
                                     instance.image_ref)
        self._try_fetch_image(context, container_image, instance)

        try:
            self._create_image(instance, container_image)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Error downloading image from glance: %(instance)s %(image)s'),
                {'instance': instance.uuid,
                 'image': instance.image_ref})

        try:
            self._create_rootfs(instance)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Error creating rootfs: %(instance)s %(image)s'),
                          {'instance': instance.uuid,
                           'image': instance.image_ref})

    def _try_fetch_image(self, context, image, instance, max_size=0):
        try:
            if os.path.exists(self.image_dir):
                return

            images.fetch_to_raw(context, instance.image_ref, image,
                                instance.user_id, instance.project_id,
                                max_size=max_size)
        except exception.ImageNotFound:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE("Image %(image_id)s doesn't exist anymore on "
                          "image service, attempting to copy image ",
                          {'image_id': instance.image_ref}))

    def _create_image(self, instance, container_image):
        LOG.debug(_('Create image'))
        try:
            if not os.path.exists(self.image_dir):
                fileutils.ensure_tree(self.image_dir)

                (user, group) = self.idmap.get_user()

                utils.execute('chown', '%s:%s' % (user, group),
                              self.image_dir, run_as_root=True)
                tar = ['tar', '--directory', self.image_dir,
                       '--anchored', '--numeric-owner', '-xpzf', container_image]
                nsexec = (['lxc-usernsexec'] +
                          self.idmap.usernsexec_margs(with_read="user") +
                          ['--'])
                args = tuple(nsexec + tar)
                utils.execute(*args, check_exit_code=[0, 2])
                utils.execute(*tuple(nsexec + ['chown', '0:0', self.image_dir]))
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.exception(_LE('Failed to create image %(instance)s'),
                              {'instnace': instance.uuid})

    def _create_rootfs(self,instance):
        LOG.debug(_('Creating container rootfs'))
        try:
            if os.path.exists(self.image_dir):
                self.rootfs_dir = os.path.join(CONF.lxd.lxd_root_dir,
                                              instance.uuid, 'rootfs')
                if not os.path.exists(self.rootfs_dir):
                    utils.execute('mkdir', '-p', self.rootfs_dir,
                                  run_as_root=True)

                self.upper_dir = os.path.join(CONF.lxd.lxd_root_dir,
                                              instance.uuid, 'rootfs')
                if not os.path.exists(self.upper_dir):
                    utils.execute('mkdir', '-p', self.upper_dir,
                                  run_as_root=True)

                if not os.path.exists(self.work_dir):
                    utils.execute('mkdir', '-p', self.workd_dir,
                                  run_as_root=True)

                utils.execute('mount', '-t', 'overlay', 'overlay',
                              '-o',
                              'lowerdir=%s,upperdir=%s,workdir=%s'
                               %(self.image_dir, self.upper_dir,
                                 self.work_dir),
                                 self.rootfs_dir,
                                 run_as_root=True)

                (user, group) = self.idmap.get_user()
                utils.execute('chown', '-R', '%s:%s' % (user, group),
                              self.rootfs_dir, run_as_root=True)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE("Failed to create rootfs %(instance)s"),
                         {'instance': instance.uuid})
