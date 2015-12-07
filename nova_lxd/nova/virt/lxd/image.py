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

from nova_lxd.nova.virt.lxd.session import session
from nova_lxd.nova.virt.lxd import utils as container_dir

_ = i18n._
_LE = i18n._LE

CONF = cfg.CONF
LOG = logging.getLogger(__name__)
IMAGE_API = image.API()


class LXDContainerImage(object):
    """Upload an image from glance to the local LXD image store."""

    def __init__(self):
        self.connection = api.API()
        self.client = session.LXDAPISession()
        self.container_dir = container_dir.LXDContainerDirectories()
        self.lock_path = str(os.path.join(CONF.instances_path, 'locks'))

    def setup_image(self, context, instance, image_meta):
        """Download an image from glance and upload it to LXD

        :param context: context object
        :param instance: The nova instance
        :param image_meta: Image dict returned by nova.image.glance

        """
        LOG.debug('setup_image called for instance', instance=instance)
        try:
            with lockutils.lock(self.lock_path,
                                lock_file_prefix=('lxd-image-%s' %
                                                  instance.image_ref),
                                external=True):

                if self.client.image_defined(instance):
                    return

                base_dir = self.container_dir.get_base_dir()
                if not os.path.exists(base_dir):
                    fileutils.ensure_tree(base_dir)

                container_rootfs_img = (
                    self.container_dir.get_container_rootfs_image(
                        image_meta))
                self._fetch_image(context, image_meta, instance)

                container_manifest_img = self._get_lxd_manifest(instance,
                                                                image_meta)
                utils.execute('xz', '-9', container_manifest_img)

                self._image_upload(
                    (container_manifest_img + '.xz', container_rootfs_img),
                    container_manifest_img.split('/')[-1],
                    instance)

                self._setup_alias((container_manifest_img + '.xz',
                                   container_rootfs_img), instance)

                os.unlink(container_manifest_img + '.xz')

        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Failed to upload %(image)s to LXD: %(reason)s'),
                          {'image': instance.image_ref, 'reason': ex},
                          instance=instance)
                self._cleanup_image(image_meta, instance)

    def _fetch_image(self, context, image_meta, instance):
        """Fetch an image from glance

        :param context: nova security object
        :param image_meta: glance image dict
        :param instance: the nova instance object

        """
        LOG.debug('_fetch_iamge called for instance', instance=instance)
        path = self.container_dir.get_container_rootfs_image(
            image_meta)
        with fileutils.remove_path_on_error(path):
            IMAGE_API.download(context, instance.image_ref, dest_path=path)

    def _get_lxd_manifest(self, instance, image_meta):
        """Creates the LXD manifest, needed for split images

        :param instance: nova instance
        :param image_meta: image metadata dictionary

        """
        LOG.debug('_get_lxd_manifest called for instance', instance=instance)

        try:
            container_manifest = (
                self.container_dir.get_container_manifest_image(
                    image_meta))

            target_tarball = tarfile.open(container_manifest, "w:")

            image_prop = image_meta.get('properties')
            metadata = {
                'architecture': image_prop.get('architecture',
                                               os.uname()[4]),
                'creation_date': int(os.stat(container_manifest).st_ctime),
                'properties': {
                    'os': image_prop.get('os_distro', 'None'),
                    'architecture': image_prop.get('architecture',
                                                   os.uname()[4]),
                    'description': image_prop.get('description',
                                                  None),
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
                self._cleanup_image(image_meta, instance)

    def _image_upload(self, path, filename, instance):
        """Upload an image to the LXD image store

        :param path: path to the glance image
        :param filenmae: name of the file
        :param instance: nova instance

        """
        LOG.debug('image_upload called for instance', instance=instance)
        headers = {}

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

        self.client.image_upload(data=body, headers=headers,
                                 instance=instance)

    def _setup_alias(self, path, instance):
        """Creates the LXD alias for the image

        :param path: fileystem path of the glance image
        :param instance: nova instance
        """
        LOG.debug('_setup_alias called for instance', instance=instance)

        try:
            meta_path, rootfs_path = path
            with open(meta_path, 'rb') as meta_fd:
                with open(rootfs_path, "rb") as rootfs_fd:
                    fingerprint = hashlib.sha256(meta_fd.read() +
                                                 rootfs_fd.read()).hexdigest()
            alias_config = {
                'name': instance.image_ref,
                'target': fingerprint
            }
            self.client.create_alias(alias_config, instance)
        except lxd_exceptions.APIError as ex:
            raise exception.ImageUnacceptable(
                image_id=instance.image_ref,
                reason=_('Image already exists: %s') % ex)

    def _cleanup_image(self, image_meta, instance):
        """Cleanup the remaning bits of the glance/lxd interaction

        :params image_meta: image_meta dictionary

        """
        LOG.debug('_cleanup_image called for instance', instance=instance)
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
