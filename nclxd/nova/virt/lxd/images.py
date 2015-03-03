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
import hashlib

from oslo.config import cfg
from oslo_log import log as logging
from oslo_utils import excutils

from nova.i18n import _, _LE
from nova.openstack.common import fileutils
from nova.virt import images
from nova import exception


CONF = cfg.CONF
LOG = logging.getLogger(__name__)


class ContainerImage(object):
    def __init__(self, context, instance, image_meta, client):
        self.context = context
        self.image_meta = image_meta
        self.instance = instance
        self.client = client
        self.max_size = 0

        self.base_dir = os.path.join(CONF.instances_path,
                                     CONF.image_cache_subdirectory_name)
        self.container_image = os.path.join(self.base_dir,
                                            '%s.tar.gz' % self.instance['image_ref'])

        if not os.path.exists(self.base_dir):
            fileutils.ensure_tree(self.base_dir)

    def upload_image(self):
        LOG.info(_('Downloading image from glance'))

        disk_format = self.image_meta.get('disk_format')
        if disk_format != 'root-tar' or disk_format is None:
            msg = _('Unable to determine disk format for image.')
            raise exception.InvalidImageRef(msg)

        if not os.path.exists(self.container_image):
            LOG.info(_('Fetching Image from Glance'))
            try:
                images.fetch_to_raw(self.context, self.instance['image_ref'], self.container_image,
                                    self.instance['user_id'], self.instance['project_id'],
                                    max_size=self.max_size)
                fingerprint = self._get_fingerprint()

                if fingerprint in self.client.list_images():
                    msg = _('Image already exists in LXD store')
                    raise exception.InvalidImageRef(msg)

                self.client.upload_image(self.container_image, self.container_image.split('/')[-1])

                if self.instance['image_ref'] in self.client.list_aliases():
                    msg = _('Alias already exists in LXD store')
                    raise exception.InvalidImageRef(msg)

                self.client.alias_create(self.instance['image_ref'], fingerprint)
                os.unlink(self.container_image)
            except Exception:
                with excutils.save_and_reraise_exception():
                    LOG.error(_LE('Erorr uploading image to image store for %(image).'),
                                 {'image': self.instance['image_ref']})
                    self.cleanup_image()

    def cleanup_image(self):
        LOG.info(_('Cleaning up image'))

        if os.path.exists(self.container_image):
            fingerprint = self._get_fingerprint()
            os.unlink(self.container_image)

        if self.instance['image_ref'] in self.client.lists_aliases():
            self.client.alias_delete(self.instance['image_ref'])

        if fingerprint is not None:
            self.client.remove_image(fingerprint)


    def _get_fingerprint(self):
        with open(self.container_image, 'rb') as fp:
            fingerprint = hashlib.sha256(fp.read()).hexdigest()
        return fingerprint