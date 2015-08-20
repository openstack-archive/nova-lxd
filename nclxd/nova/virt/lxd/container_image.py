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
import tarfile
import uuid

from nova import exception
from nova import i18n
from nova import image
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


def get_lxd_image(image_meta):
    return image_meta['properties'].get('lxd_image_alias', None)

def update_image(context, instance):
    image_meta = {
        'properties': {
            'lxd_image_alias': instance.image_ref
        }
    }
    IMAGE_API.update(context,
                     instance.image_ref,
                     image_meta)

def setup_alias(instance, data):
    lxd = api.API()

    try:
        alias_config = {
           'name': instance.image_ref,
           'target': data['metadata']['fingerprint']
        }
        LOG.debug('Creating alias: %s' % alias_config)
        lxd.alias_create(alias_config)
    except lxd_exceptions.APIError as ex:
        raise exception.ImageUnacceptable(
            image_id=instance.image_ref,
            reason=_('Image already exists: %s' % ex))

def images_upload(path, filename):
    lxd = api.API()
    headers = {}

    if isinstance(path, str):
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

class LXDBaseImage(object):
    def __init__(self):
        pass

    def setup_image(self, context, instance, image_meta, host=None):
        pass

    def destroy_image(self, context, instance, image_meta):
        pass

class LXDContainerImage(LXDBaseImage):
    def __init__(self):
        self.container_client = container_client.LXDContainerClient()
        self.container_dir = container_utils.LXDContainerDirectories()

    def setup_image(self, context, instance, image_meta, host=None):
        LOG.debug('Fetching image info from LXD')

        lxd_image = get_lxd_image(image_meta)
        if lxd_image is not None:
            return 

        LOG.debug("Uploading file data %(image_ref)s to LXD",
                  {'image_ref': instance.image_ref})

        base_dir = self.container_dir.get_base_dir()
        if not os.path.exists(base_dir):
            fileutils.ensure_tree(base_dir)

        container_image = self.container_dir.get_container_image(image_meta)
        IMAGE_API.download(context, instance.image_ref, dest_path=container_image)

        ''' Upload LXD image(s) '''
        (target_metadata, target_rootfs) = self._get_image_contents(container_image, 
                                                                    image_meta)
        data = images_upload((target_metadata, target_rootfs),
                              target_metadata.split('/')[-1])
        setup_alias(instance, data)
        update_image(context, instance)

    def _get_image_contents(self, container_image, image_meta):
        LOG.debug('Extracting LXD files')

        base_dir = self.container_dir.get_base_dir()
        with tarfile.open(container_image, mode='r') as tar:
            for tar_info in tar:
                if tar_info.name.endswith('-lxd.tar.xz'):
                    target_metadata = os.path.join(base_dir, tar_info.name)
                    tar.extract(tar_info.name,
                                path=base_dir)
                elif tar_info.name.endswith('-root.tar.xz'):
                    target_rootfs = os.path.join(base_dir, tar_info.name)
                    tar.extract(tar_info.name, 
                                path=base_dir)
            return (target_metadata, target_rootfs)

    def destroy_image(self, context, instance, image_meta):
        pass

class LXDOpenStackImage(LXDBaseImage):

    def __init__(self):
        self.container_dir = container_utils.LXDContainerDirectories()

    def setup_image(self, context, instance, image_meta, host=None):
        lxd_image = get_lxd_image(image_meta)
        if lxd_image is not None:
                return

        LOG.debug("Uploading image file data %(image_ref)s to LXD",
                      {'image_ref': instance.image_ref})

        base_dir = self.container_dir.get_base_dir()
        if not os.path.exists(base_dir):
            fileutils.ensure_tree(base_dir)

        container_image = self.container_dir.get_container_image(image_meta)
        IMAGE_API.download(context, instance.image_ref, dest_path=container_image)

        ''' Upload the image to LXD '''
        data = upload_image(container_image, container_image.split("/")[-1])
        setup_alias(container_image, data)
        update_image(context, instance)

    def destroy_image(self):
        pass

