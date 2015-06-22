import hashlib
import os

from oslo_config import cfg
from oslo_log import log as logging

from pylxd import api
from pylxd import exceptions as lxd_exceptions

from nova.i18n import _
from nova.openstack.common import fileutils
from nova import image
from nova import exception
from nova import utils

import container_config
import container_utils

CONF = cfg.CONF
LOG = logging.getLogger(__name__)
IMAGE_API = image.API()


class LXDContainerImage(object):

    def __init__(self):
        self.lxd = api.API()
        self.container_dir = container_utils.LXDContainerDirectories()

    def fetch_image(self, context, instance):
        LOG.debug("Downloading image file data %(image_ref)s to LXD",
                  {'image_ref': instance.image_ref})
        base_dir = self.container_dir.get_base_dir()
        if not os.path.exists(base_dir):
            fileutils.ensure_tree(base_dir)

        container_image = self.container_dir.get_container_image(instance)
        if os.path.exists(container_image):
            return

        IMAGE_API.download(context, instance.image_ref,
                           dest_path=container_image)

        ''' Upload the image to LXD '''
        with fileutils.remove_path_on_error(container_image):
            try:
                self.lxd.image_defined(instance.image_ref)
            except lxd_exceptions.APIError as e:
                if e.status_code == 404:
                    pass
                else:
                    raise exception.ImageUnacceptable(image_id=instance.image_ref,
                                                      reason=_('Image already exists.'))

            try:
                LOG.debug('Uploading image: %s' % container_image)
                self.lxd.image_upload(path=container_image)
            except lxd_exceptions.APIError as e:
                raise exception.ImageUnacceptable(
                    image_id=instance.image_ref,
                    reason=_('Image failed to upload: %s' % e))

            try:
                alias_config = {'name': instance.image_ref,
                                'target': self.get_container_image_md5(instance)
                                }
                LOG.debug('Creating alias: %s' % alias_config)
                self.lxd.alias_create(alias_config)
            except lxd_exceptions.APIError:
                raise exception.ImageUnacceptable(image_id=instance.image_ref,
                                                  reason=_('Image already exists.'))

    def get_container_image_md5(self, instance):
        container_image = self.container_dir.get_container_image(instance)
        with open(container_image, 'rb') as fd:
            return hashlib.sha256(fd.read()).hexdigest()
