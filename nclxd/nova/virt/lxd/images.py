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
import hashlib
import time
import tarfile
import tempfile

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
    def __init__(self, context, instance, image_meta, client):
        self.context = context
        self.image_meta = image_meta
        self.instance = instance
        self.client = client
        self.max_size = 0

        self.base_dir = os.path.join(CONF.instances_path,
                                     CONF.image_cache_subdirectory_name)
        self.container_image = os.path.join(self.base_dir,
                                            '%s.tar.gz' % self.instance.image_ref)
        self.metadata = {}
        self.workdir = tempfile.mkdtemp()

        if not os.path.exists(self.base_dir):
            fileutils.ensure_tree(self.base_dir)

    def fetch_image(self):
        LOG.info(_('Downloading image from glance'))

        disk_format = self.image_meta.get('disk_format')
        if disk_format != 'root-tar' or disk_format is None:
            msg = _('Unable to determine disk format for image.')
            raise exception.InvalidImageRef(msg)

        if not os.path.exists(self.container_image):
            LOG.info(_('Fetching Image from Glance'))
            images.fetch_to_raw(self.context, self.instance.image_ref, self.container_image,
                                self.instance.user_id, self.instance.project_id,
                                max_size=self.max_size)

            LOG.info(_('Creating LXD image'))
            self._create_image()

    def cleanup_image(self):
        LOG.info(_('Cleaning up image'))

        if os.path.exists(self.container_image):
            fingerprint = self._get_fingerprint()
            os.unlink(self.container_image)

        if self.instance['image_ref'] in self.client.list_aliases():
            self.client.alias_delete(self.instance['image_ref'])

        if fingerprint is not None:
            self.client.remove_image(fingerprint)

    def _create_image(self):
        self._generate_metadata_info()
        self._add_metadata()
        self._upload_image()

    def _generate_metadata_info(self):
        ''' Generate LXD metadata understands '''
        LOG.info(_('Generating metadata for LXD image'))

        ''' Extract the information from the glance image '''
        variant = 'Default'
        img_meta_prop = self.image_meta.get('properties', {}) if self.image_meta else {}
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
                'variant': 'Default',
                'description': "%s %s %s Default (%s)" %
                               (os_distro,
                                os_release,
                                architecture,
                                os_version),
                'name': self.instance['image_ref']
            },
        }

    def _upload_image(self):
        LOG.debug(_('Uploading image to LXD'))

        fingerprint = self._get_fingerprint()

        if fingerprint in self.client.list_images():
            msg = _('Image already exists.')
            raise exception.InvalidImageRef(msg)

        self.client.upload_image(self.container_image, self.container_image.split('/')[-1])

        if self.instance.image_ref in self.client.list_aliases():
            msg = _('Alias already exists')
            raise exception.InvalidImageRef(msg)

        self.client.create_alias(self.instance.image_ref, fingerprint)

    def _add_metadata(self):
        LOG.debug(_('Adding metadata file'))

        target_image = os.path.join(self.base_dir,
                                            '%s.tar' % self.instance.image_ref)
        utils.execute('gunzip', self.container_image)

        metadata_yaml = json.dumps(self.metadata, sort_keys=True,
                           indent=4, separators=(',', ': '),
                           ensure_ascii=False).encode('utf-8') + b"\n"
        metadata_file = os.path.join(self.workdir, 'metadata.yaml')
        with open(metadata_file, 'w') as fp:
            fp.write(metadata_yaml)
        utils.execute('tar', '-C', self.workdir,'-rf', target_image, 'metadata.yaml')
        utils.execute('gzip', target_image)

    def _get_fingerprint(self):
        with open(self.container_image, 'rb') as fp:
            fingerprint = hashlib.sha256(fp.read()).hexdigest()
        return fingerprint