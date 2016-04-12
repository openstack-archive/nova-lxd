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
from nova.compute import arch
from nova import exception
from nova import i18n
from nova import image
from nova import utils
import os
import shutil
import tarfile
import tempfile
import uuid

from oslo_concurrency import lockutils
from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import fileutils

from nova_lxd.nova.virt.lxd import session
from nova_lxd.nova.virt.lxd import utils as container_dir

_ = i18n._
_LE = i18n._LE

CONF = cfg.CONF
LOG = logging.getLogger(__name__)
IMAGE_API = image.API()


class LXDContainerImage(object):
    """Upload an image from glance to the local LXD image store."""

    def __init__(self):
        self.client = session.LXDAPISession()
        self.container_dir = container_dir.LXDContainerDirectories()
        self.lock_path = str(os.path.join(CONF.instances_path, 'locks'))

        self.container_image = None
        self.container_manifest = None

    def setup_image(self, context, instance, image_meta):
        """Download an image from glance and upload it to LXD

        :param context: context object
        :param instance: The nova instance
        :param image_meta: Image dict returned by nova.image.glance
        """
        LOG.debug('setup_image called for instance', instance=instance)

        self.container_image = \
            self.container_dir.get_container_rootfs_image(image_meta)
        self.container_manifest = \
            self.container_dir.get_container_manifest_image(image_meta)

        with lockutils.lock(self.lock_path,
                            lock_file_prefix=('lxd-image-%s' %
                                              instance.image_ref),
                            external=True):

            if self.client.image_defined(instance):
                return

            base_dir = self.container_dir.get_base_dir()
            if not os.path.exists(base_dir):
                fileutils.ensure_tree(base_dir)

            try:
                # Inspect image for the correct format
                self._verify_image(context, instance)

                # Fetch the image from glance
                self._fetch_image(context, instance)

                # Generate the LXD manifest for the image
                self._get_lxd_manifest(instance, image_meta)

                # Upload the image to the local LXD image store
                self._image_upload(instance)

                # Setup the LXD alias for the image
                self._setup_alias(instance)

                # Remove image and manifest when done.
                self._cleanup_image(instance)

            except Exception as ex:
                with excutils.save_and_reraise_exception():
                    LOG.error(_LE('Failed to upload %(image)s to LXD: '
                                  '%(reason)s'),
                              {'image': instance.image_ref,
                               'reason': ex}, instance=instance)
                    self._cleanup_image(instance)

    def _verify_image(self, context, instance):
        """Inspect image to verify the correct disk format.

          Inspect and verify and the image that will downloaded
          from glance is the correct image. The image must be in
          a raw disk format in order for the LXD daemon to import
          it into the local image store.

          :param context: nova security context
          ;param instance: nova instance object
        """
        LOG.debug('_verify_image called for instance', instance=instance)
        try:
            # grab the disk format of the image
            img_meta = IMAGE_API.get(context, instance.image_ref)
            disk_format = img_meta.get('disk_format')
            if not disk_format:
                reason = _('Bad image format')
                raise exception.ImageUnacceptable(image_id=instance.image_ref,
                                                  reason=reason)

            if disk_format not in ['raw', 'root-tar']:
                reason = _('nova-lxd does not support images in %s format. '
                           'You should upload an image in raw or root-tar '
                           'format.') % disk_format
                raise exception.ImageUnacceptable(image_id=instance.image_ref,
                                                  reason=reason)
        except Exception as ex:
            reason = _('Bad Image format: %(ex)s') \
                % {'ex': ex}
            raise exception.ImageUnacceptable(image_id=instance.image_ref,
                                              reason=reason)

    def _fetch_image(self, context, instance):
        """Fetch an image from glance

        :param context: nova security object
        :param instance: the nova instance object

        """
        LOG.debug('_fetch_image called for instance', instance=instance)
        with fileutils.remove_path_on_error(self.container_image):
            IMAGE_API.download(context, instance.image_ref,
                               dest_path=self.container_image)

    def _get_lxd_manifest(self, instance, image_meta):
        """Creates the LXD manifest, needed for split images

        :param instance: nova instance
        :param image_meta: image metadata dictionary

        """
        LOG.debug('_get_lxd_manifest called for instance', instance=instance)

        metadata_yaml = None
        try:
            # Create a basic LXD manifest from the image properties
            image_arch = image_meta.properties.get('hw_architecture')
            if image_arch is None:
                image_arch = arch.from_host()
            metadata = {
                'architecture': image_arch,
                'creation_date': int(os.stat(self.container_image).st_ctime)
            }

            metadata_yaml = (json.dumps(metadata, sort_keys=True,
                                        indent=4, separators=(',', ': '),
                                        ensure_ascii=False).encode('utf-8')
                             + b"\n")
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Failed to generate manifest for %(image)s: '
                              '%(reason)s'),
                          {'image': instance.name, 'ex': ex},
                          instance=instance)
        try:
            # Compress the manifest using tar
            target_tarball = tarfile.open(self.container_manifest, "w:")
            metadata_file = tarfile.TarInfo()
            metadata_file.size = len(metadata_yaml)
            metadata_file.name = "metadata.yaml"
            target_tarball.addfile(metadata_file,
                                   io.BytesIO(metadata_yaml))
            target_tarball.close()
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Failed to generate manifest tarball for'
                              ' %(image)s: %(reason)s'),
                          {'image': instance.name, 'ex': ex},
                          instance=instance)

        try:
            # Compress the manifest further using xz
            with fileutils.remove_path_on_error(self.container_manifest):
                utils.execute('xz', '-9', self.container_manifest,
                              check_exit_code=[0, 1])
        except processutils.ProcessExecutionError as ex:
            with excutils.save_and_reraise_exception:
                LOG.error(_LE('Failed to compress manifest for %(image)s:'
                              ' %(ex)s'), {'image': instance.image_ref,
                                           'ex': ex}, instance=instance)

    def _image_upload(self, instance):
        """Upload an image to the LXD image store

        We create the LXD manifest on the fly since glance does
        not understand how to talk to Glance.

        :param instance: nova instance

        """
        LOG.debug('image_upload called for instance', instance=instance)
        headers = {}

        boundary = str(uuid.uuid1())

        # Create the binary blob to upload the file to LXD
        tmpdir = tempfile.mkdtemp()
        upload_path = os.path.join(tmpdir, "upload")
        body = open(upload_path, 'wb+')

        for name, path in [("metadata", (self.container_manifest + '.xz')),
                           ("rootfs", self.container_image)]:
            filename = os.path.basename(path)
            body.write(bytearray("--%s\r\n" % boundary, "utf-8"))
            body.write(bytearray("Content-Disposition: form-data; "
                                 "name=%s; filename=%s\r\n" %
                                 (name, filename), "utf-8"))
            body.write("Content-Type: application/octet-stream\r\n")
            body.write("\r\n")
            with open(path, "rb") as fd:
                shutil.copyfileobj(fd, body)
            body.write("\r\n")

        body.write(bytearray("--%s--\r\n" % boundary, "utf-8"))
        body.write('\r\n')
        body.close()

        headers['Content-Type'] = "multipart/form-data; boundary=%s" \
            % boundary

        # Upload the file to LXD and then remove the tmpdir.
        self.client.image_upload(data=open(upload_path, 'rb'),
                                 headers=headers, instance=instance)
        shutil.rmtree(tmpdir)

    def _setup_alias(self, instance):
        """Creates the LXD alias for the image

        :param instance: nova instance
        """
        LOG.debug('_setup_alias called for instance', instance=instance)

        try:
            with open((self.container_manifest + '.xz'), 'rb') as meta_fd:
                with open(self.container_image, "rb") as rootfs_fd:
                    fingerprint = hashlib.sha256(meta_fd.read() +
                                                 rootfs_fd.read()).hexdigest()
            alias_config = {
                'name': instance.image_ref,
                'target': fingerprint
            }
            self.client.create_alias(alias_config, instance)
        except Exception as ex:
            with excutils.save_and_reraise_exception:
                LOG.error(_LE('Failed to setup alias for %(image)s:'
                              ' %(ex)s'), {'image': instance.image_ref,
                                           'ex': ex}, instance=instance)

    def _cleanup_image(self, instance):
        """Cleanup the remaning bits of the glance/lxd interaction

        :params image_meta: image_meta dictionary

        """
        LOG.debug('_cleanup_image called for instance', instance=instance)

        if os.path.exists(self.container_image):
            os.unlink(self.container_image)

        if os.path.exists(self.container_manifest):
            os.unlink(self.container_manifest)
