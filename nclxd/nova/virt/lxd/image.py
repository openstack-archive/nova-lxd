# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# Copyright (c) 2010 Citrix Systems, Inc.
# Copyright 2011 Justin Santa Barbara
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

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import importutils

from nova.i18n import _, _LE
from nova import exception
from nova.openstack.common import fileutils
from nova import utils

import container_utils

CONF = cfg.CONF
LOG = logging.getLogger(__name__)


def load_driver(default, *args, **kwargs):
    image_class = importutils.import_class(CONF.lxd.lxd_image_type)
    return image_class(*args, **kwargs)


def fetch_image(client, context, image, instance):
    try:
        if image not in client.image_list():
            if not os.path.exists(container_utils.get_base_dir()):
                fileutils.ensure_tree(container_utils.get_base_dir())
            container_image = container_utils.get_container_image(
                                instance)
            container_utils.fetch_image(context, container_image, instance)
    except Exception:
        with excutils.save_and_reraise_exception():
                LOG.error(_LE('Error downloading image: %(instance)'
                              ' %(image)s'),
                              {'instance': instance.uuid,
                              'image': instance.image_ref})

class BaseContainerImage(object):
    def __init__(self, lxd):
        self.lxd = lxd

    def setup_container(self, context, instance, image_meta):
        pass

    def destory_contianer(self, instance, image_meta):
        pass


class DefaultContainerImage(object):
    def __init__(self, lxd):
        self.lxd = lxd

    def setup_container(self, context, instance, image_meta):
        LOG.debug("Setting up Container")
        container_image = container_utils.get_container_image(instance)
        try:
            if instance.image_ref in self.lxd.image_list():
                return

            if os.path.exists(container_image):
                return

            fetch_image(self.lxd, context,
                        instance.image_ref, instance)
            self._upload_image(container_image, instance, image_meta)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.exception(_LE('Failed to setup container: %s = %s'),
                               (instance.uuid, ex))
                self.destroy_contianer(instance, image_meta)
                raise

    def _upload_image(self, container_image, instance, image_meta):
        if not self._check_image_file(container_image, image_meta):
            msg = _('md5checksum mismtach')
            raise exception.NovaException(msg)

        if not self.lxd.image_upload(container_image,
                                 container_image.split('/')[-1]):
            msg = _('Image upload failed')
            raise exception.NovaException(msg)

        config = {'target': self._get_lxd_md5sum(container_image),
                  'name': instance.image_ref}
        if not self.lxd.alias_create(config):
            msg = _('Alias creation failed')
            raise exception.NovaException(msg)

    def _check_image_file(self, container_image, image_meta):
        md5sum = self._get_glance_md5sum(container_image)
        if image_meta.get('checksum') == md5sum:
            return True
        else:
            return False

    def _get_glance_md5sum(self, container_image):
        out, err = utils.execute('md5sum', container_image)
        return out.split(' ')[0]

    def _get_lxd_md5sum(self, container_image):
        with open(container_image, 'rb') as fd:
            return hashlib.sha256(fd.read()).hexdigest()

    def _image_rollback(self, container_image):
        if os.path.exists(container_image):
            os.unlink(container_image)

    def destroy_container(self, instance, image_meta):
        LOG.debug('Destroying container')

        container_image = container_utils.get_container_image(instance)
        if instance.image_ref in self.lxd.alias_list():
            self.lxd.alias_delete(instance.image_ref)

        fingerprint = self._get_lxd_md5sum(container_image)
        if fingerprint in self.lxd.image_list():
            self.lxd.image_delete(fingerprint)

        if os.path.exists(container_image):
            os.unlink(container_image)
