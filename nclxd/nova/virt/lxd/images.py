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
import json
import time
import tempfile
import shutil

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
    def __init__(self, client):
        self.client = client
        self.metadata = {}

        self.base_dir = os.path.join(CONF.instances_path,
                                     CONF.image_cache_subdirectory_name)
        self.workdir = tempfile.mkdtemp()

    def fetch_image(self, context, instance, image_meta):
        LOG.debug(_('Fetching image from glance'))

        disk_format = image_meta.get('disk_format')
        if disk_format != 'root-tar' or disk_format is None:
            msg = _('Unable to determine disk format for image.')
            raise exception.InvalidImageRef(msg)

        container_image = os.path.join(self.base_dir,
                                       '%s.tar.gz' % instance.image_ref)
        if not os.path.exists(container_image):
            fileutils.ensure_tree(self.base_dir)
            self._try_fetch_image(context, container_image, instance)

            LOG.debug(_('Upload image to LXD'))
            self._get_image_metadata(instance, image_meta)
            self._update_image(instance, image_meta, container_image)
            if instance.image_ref not in self.client.alias_list():
                fingerprint = self._create_image(instance, container_image)
                self._create_alias(instance, fingerprint)

    def _try_fetch_image(self, context, image, instance, max_size=0):
        try:
            images.fetch_to_raw(context, instance.image_ref, image,
                                instance.user_id, instance.project_id,
                                max_size=max_size)
        except exception.ImageNotFound:
            LOG.debug("Image %(image_id)s doesn't exist anymore on "
                      "image service, attempting to copy image ",
                      {'image_id': image_id})

    def _get_image_metadata(self, instance, image_meta):
        ''' Generate LXD metadata understands '''
        LOG.info(_('Generating metadata for LXD image'))

        ''' Extract the information from the glance image '''
        variant = 'Default'
        img_meta_prop = image_meta.get('properties', {}) if image_meta else {}
        architecture  = img_meta_prop.get('architecture', '')
        if not architecture:
            raise exception.NovaException(_('Unable to determine architecture.'))


        os_distro = img_meta_prop.get('os_distro')
        if not os_distro:
            raise exception.NovaException(_('Unable to distribution.'))

        os_version = img_meta_prop.get('os_version')
        if not os_version:
            raise exception.NovaException(_('Unable to determine version.'))

        os_release = img_meta_prop.get('os_release')
        if not os_release:
            raise exception.NovaException(_('Unable to determine release '))
        epoch = time.time()

        self.metadata = {
            'architecture': architecture,
            'creation_date': int(epoch),
            'properties': {
                'os': os_distro,
                'release': os_release,
                'architecture': architecture,
                'variant': variant,
                'description': "%s %s %s Default (%s)" %
                               (os_distro,
                                os_release,
                                architecture,
                                os_version),
                'name': instance['image_ref']
            },
        }

    def _update_image(self,instance, image_meta, container_image):
        rootfs_dir = os.path.join(self.workdir, 'rootfs')

        fileutils.ensure_tree(rootfs_dir)
        utils.execute('tar', '-zxvf', container_image, '-C', rootfs_dir,
                      run_as_root=True, check_exit_code=[0, 2])

        metadata_yaml = json.dumps(self.metadata, sort_keys=True,
                           indent=4, separators=(',', ': '),
                           ensure_ascii=False).encode('utf-8') + b"\n"
        metadata_file = os.path.join(self.workdir, 'metadata.yaml')
        with open(metadata_file, 'w') as fp:
            fp.write(metadata_yaml)
        utils.execute('tar', '-C', self.workdir, '-zcvf',
                      container_image, 'metadata.yaml', 'rootfs',
                      run_as_root=True, check_exit_code=[0, 2])

    def _create_image(self, instance, container_image):
        try:
            LOG.debug(_('Uploading image to LXD image store'))
            (status, resp) = self.client.image_upload(container_image,
                                                      container_image.split('/')[-1])
            if resp.get('status') == 'error':
                raise exception.NovaException
            return resp.get('metadata')['fingerprint']
        except Exception as e:
            LOG.debug(_('Failed to create alias: %s') % resp.get('metadata'))
            msg = _('Cannot create image: {0}')
            raise exception.NovaException(msg.format(e),
                                          instance_id=instance.name)
    def _create_alias(self, instance, fingerprint):
        try:
            LOG.debug(_('Creating LXD profile'))
            (status, resp) = self.client.alias_create(instance.image_ref, fingerprint)
            if resp.get('status') == 'error':
                raise exception.NovaException
        except Exception as e:
            LOG.debug(_('Failed to create alias: %s') % resp.get('metadata'))
            msg = _('Cannot create profile: {0}')
            raise exception.NovaException(msg.format(e),
                                          instance_id=instance.name)