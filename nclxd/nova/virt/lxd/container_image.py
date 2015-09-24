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


import hashlib
import os
import uuid

from nova import exception
from nova import i18n
from nova import image
from oslo_concurrency import lockutils
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import fileutils
from pylxd import api
from pylxd import exceptions as lxd_exceptions

from nclxd.nova.virt.lxd import container_utils
from nclxd.nova.virt.lxd import container_client

_ = i18n._

CONF = cfg.CONF
LOG = logging.getLogger(__name__)
IMAGE_API = image.API()


class LXDContainerImage(object):

    def __init__(self):
        self.container_client = container_client.LXDContainerClient()
        self.container_dir = container_utils.LXDContainerDirectories()
        self.lock_path = str(os.path.join(CONF.instances_path, 'locks'))

    def setup_image(self, context, instance, image_meta):
        LOG.debug('Fetching image info from glance')

        with lockutils.lock(self.lock_path,
                            lock_file_prefix=('lxd-image-%s' %
                                              instance.image_ref),
                            external=True):

            if self.container_client.client('alias_defined',
                                            instance=instance.image_ref,
                                            host=instance.node):
                return

            base_dir = self.container_dir.get_base_dir()
            if not os.path.exists(base_dir):
                fileutils.ensure_tree(base_dir)

            container_rootfs_img = (
                self.container_dir.get_container_rootfs_image(
                    image_meta))
            if os.path.exists(container_rootfs_img):
                os.remove(container_rootfs_img)

            IMAGE_API.download(
                context, instance.image_ref, dest_path=container_rootfs_img)
            lxd_image_manifest = self._get_lxd_manifest(image_meta)
            if lxd_image_manifest is not None:
                container_manifest_img = (
                    self.container_dir.get_container_manifest_image(
                        image_meta))
                if os.path.exists(container_manifest_img):
                    os.remove(container_manifest_img)

                IMAGE_API.download(context, lxd_image_manifest,
                                   dest_path=container_manifest_img)
                img_info = self._image_upload(
                    (container_manifest_img, container_rootfs_img),
                               container_manifest_img.split('/')[-1], False,
                               instance)
            else:
                img_info = self._image_upload(container_rootfs_img,
                                              container_rootfs_img.split(
                                                  "/")[-1], True,
                                              instance)

            self._setup_alias(instance, img_info, image_meta, context)

    def _get_lxd_manifest(self, image_meta):
        return image_meta['properties'].get('lxd_manifest', None)

    def _image_upload(self, path, filename, split, instance):
        LOG.debug('Uploading Image to LXD.')
        lxd = api.API()
        headers = {}

        if split:
            headers['Content-Type'] = "application/octet-stream"

            try:
                status, data = lxd.image_upload(data=open(path, 'rb'),
                                                headers=headers)
            except lxd_exceptions as ex:
                raise exception.ImageUnacceptable(
                    image_id=instance.image_ref,
                    reason=_('Failed to upload image: %s' % ex))
        else:
            meta_path, rootfs_path = path
            boundary = str(uuid.uuid1())

            form = []
            for name, path in [("metadata", meta_path),
                               ("rootfs", rootfs_path)]:
                filename = os.path.basename(path)
                form.append("--%s" % boundary)
                form.append("Content-Disposition: form-data; "
                            "name=%s; filename=%s" % (name, filename))
                form.append("Content-Type: application/octet-stream")
                form.append("")
                with open(path, "rb") as fd:
                    form.append(fd.read())

            form.append("--%s--" % boundary)
            form.append("")

            body = b""
            for entry in form:
                if isinstance(entry, bytes):
                    body += entry + b"\r\n"
                else:
                    body += entry.encode() + b"\r\n"

            headers['Content-Type'] = "multipart/form-data; boundary=%s" \
                % boundary

            try:
                status, data = lxd.image_upload(data=body,
                                                headers=headers)
            except lxd_exceptions as ex:
                raise exception.ImageUnacceptable(
                    image_id=instance.image_ref,
                    reason=_('Failed to upload image: %s' % ex))

        return data

    def _setup_alias(self, instance, img_info, image_meta, context):
        LOG.debug('Updating image and metadata')

        lxd = api.API()
        try:
            alias_config = {
                'name': instance.image_ref,
                'target': img_info['metadata']['fingerprint']
            }
            LOG.debug('Creating alias: %s' % alias_config)
            lxd.alias_create(alias_config)
        except lxd_exceptions.APIError as ex:
            raise exception.ImageUnacceptable(
                image_id=instance.image_ref,
                reason=_('Image already exists: %s' % ex))
