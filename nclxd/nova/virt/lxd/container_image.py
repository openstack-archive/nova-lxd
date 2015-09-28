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
from nova import i18n
from nova import image
from nova import utils
import os
from pylxd import api
from pylxd import exceptions as lxd_exceptions
import tarfile
import uuid

from oslo_concurrency import lockutils
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import fileutils

from nclxd.nova.virt.lxd import container_utils

_ = i18n._
_LE = i18n._LE

CONF = cfg.CONF
LOG = logging.getLogger(__name__)
IMAGE_API = image.API()


class LXDContainerImage(object):
    def __init__(self):
        self.connection = api.API()
        self.container_dir = container_utils.LXDContainerDirectories()
        self.lock_path = str(os.path.join(CONF.instances_path, 'locks'))

    def setup_image(self, context, instance, image_meta):
        try:
            LOG.debug('Fetching image info from glance')
            with lockutils.lock(self.lock_path,
                                lock_file_prefix=('lxd-image-%s' %
                                                  instance.image_ref),
                                external=True):

                if self._image_defined(instance):
                    return

                base_dir = self.container_dir.get_base_dir()
                if not os.path.exists(base_dir):
                    fileutils.ensure_tree(base_dir)

                container_rootfs_img = (
                    self.container_dir.get_container_rootfs_image(
                        image_meta))
                IMAGE_API.download(
                    context, instance.image_ref,
                    dest_path=container_rootfs_img)

                container_manifest_img = self._get_lxd_manifest(instance,
                                                                image_meta)
                utils.execute('xz', '-9', container_manifest_img)

                img_info = self._image_upload(
                    (container_manifest_img + '.xz', container_rootfs_img),
                    container_manifest_img.split('/')[-1], False,
                    instance)

                self._setup_alias(instance, img_info)

                os.unlink(container_manifest_img + '.xz')

        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Failed to upload %(image)s to LXD: %(reason)s'),
                          {'image': instance.image_ref, 'reason': ex},
                          instance=instance)
                self._cleanup_image(image_meta)

    def _get_lxd_manifest(self, instance, image_meta):
        LOG.debug('Creating LXD manifest')

        try:
            container_manifest = (
                self.container_dir.get_container_manifest_image(
                    image_meta))

            target_tarball = tarfile.open(container_manifest, "w:")

            metadata = {
                'architecture': image_meta.get('hw_architecture',
                                               os.uname()[4]),
                'creation_date': int(os.stat(container_manifest).st_ctime),
                'properties': {
                    'os': 'Unknown',
                    'architecture': image_meta.get('hw_architecture',
                                                   os.uname()[4]),
                    'description': ' nclxd image %s' % instance.image_ref,
                    'name': instance.image_ref
                }
            }

            metadata_yaml = (json.dumps(metadata, sort_keys=True,
                                        indent=4, separators=(',', ': '),
                                        ensure_ascii=False).encode('utf-8')
                             + b"\n")

            metadata_file = tarfile.TarInfo()
            metadata_file.size = len(metadata_yaml)
            metadata_file.name = "metadata.yaml"
            target_tarball.addfile(metadata_file,
                                   io.BytesIO(metadata_yaml))
            target_tarball.close()

            return container_manifest
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Failed to upload %(image)s to LXD: %(reason)s'),
                          {'image': instance.image_ref, 'reason': ex},
                          instance=instance)
                self._cleanup_image(image_meta)

    def _image_upload(self, path, filename, split, instance):
        LOG.debug('Uploading Image to LXD.')
        headers = {}

        if split:
            headers['Content-Type'] = "application/octet-stream"

            try:
                status, data = (self.connection.image_upload(
                    data=open(path, 'rb'),
                    headers=headers))
            except lxd_exceptions as ex:
                raise exception.ImageUnacceptable(
                    image_id=instance.image_ref,
                    reason=_('Failed to upload image: %s') % ex)
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

            headers['Content-Type'] = ("multipart/form-data; boundary=%s"
                                       % boundary)

            try:
                status, data = self.connection.image_upload(data=body,
                                                            headers=headers)
            except lxd_exceptions as ex:
                raise exception.ImageUnacceptable(
                    image_id=instance.image_ref,
                    reason=_('Failed to upload image: %s') % ex)

        return data

    def _setup_alias(self, instance, img_info):
        LOG.debug('Updating image and metadata')

        try:
            alias_config = {
                'name': instance.image_ref,
                'target': img_info['metadata']['fingerprint']
            }
            LOG.debug('Creating alias: %s' % alias_config)
            self.connection.alias_create(alias_config)
        except lxd_exceptions.APIError as ex:
            raise exception.ImageUnacceptable(
                image_id=instance.image_ref,
                reason=_('Image already exists: %s') % ex)

    def _image_defined(self, instance):
        LOG.debug('Checking alias existance')

        try:
            return self.connection.alias_defined(instance.image_ref)
        except lxd_exceptions.APIError as ex:
            if ex.status_code == 404:
                return False
            else:
                msg = _('Failed to determine image alias: %s') % ex
                raise exception.NovaException(msg)

    def _cleanup_image(self, image_meta):
        container_rootfs_img = (
            self.container_dir.get_container_rootfs_image(
                image_meta))
        container_manifest = (
            self.container_dir.get_container_manifest_image(
                image_meta))

        if os.path.exists(container_rootfs_img):
            os.unlink(container_rootfs_img)

        if os.path.exists(container_manifest):
            os.unlink(container_manifest)
