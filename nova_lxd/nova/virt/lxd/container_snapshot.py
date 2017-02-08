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
#    under the License.from oslo_config import cfg

from nova.compute import task_states
from nova import exception
from nova import i18n
from nova import image
import os

from oslo_concurrency import lockutils
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils

from nova_lxd.nova.virt.lxd import session

_ = i18n._
_LE = i18n._LE

CONF = cfg.CONF
LOG = logging.getLogger(__name__)

IMAGE_API = image.API()


class LXDSnapshot(object):

    def __init__(self):
        self.session = session.LXDAPISession()
        self.lock_path = str(os.path.join(CONF.instances_path, 'locks'))

    def snapshot(self, context, instance, image_id, update_task_state):
        """Create a LXD snapshot  of the instance

           Steps involved in creating an LXD Snapshot:

           1. Ensure the container exists
           2. Stop the LXD container: LXD requires a container
              to be stopped in or
           3. Publish the container: Run the API equivalent to
              'lxd publish container --alias <image_name>' to create
              a snapshot and upload it to the local LXD image store.
           4. Create an alias for the image: Create an alias so that
              nova-lxd can re-use the image that was created.
           5. Upload the image to glance so that it can bed on other
              compute hosts.

          :param context: nova security context
          :param instance: nova instance object
          :param image_id: glance image id
        """
        LOG.debug('snapshot called for instance', instance=instance)

        try:
            if not self.session.container_defined(instance.name, instance):
                raise exception.InstanceNotFound(instance_id=instance.name)

            with lockutils.lock(self.lock_path,
                                lock_file_prefix=('lxd-snapshot-%s' %
                                                  instance.name),
                                external=True):

                update_task_state(task_state=task_states.IMAGE_PENDING_UPLOAD)

                # We have to stop the container before we can publish the
                # image to the local store
                self.session.container_stop(instance.name,
                                            instance)
                fingerprint = self._save_lxd_image(instance,
                                                   image_id)
                self.session.container_start(instance.name, instance)

                update_task_state(task_state=task_states.IMAGE_UPLOADING,
                                  expected_state=task_states.IMAGE_PENDING_UPLOAD)  # noqa
                self._save_glance_image(context, instance, image_id,
                                        fingerprint)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Failed to create snapshot for %(instance)s: '
                              '%(ex)s'), {'instance': instance.name, 'ex': ex},
                          instance=instance)

    def _save_lxd_image(self, instance, image_id):
        """Creates an LXD image from the LXD continaer

        """
        LOG.debug('_save_lxd_image called for instance', instance=instance)

        fingerprint = None
        try:
            # Publish the snapshot to the local LXD image store
            container_snapshot = {
                "properties": {},
                "public": False,
                "source": {
                    "name": instance.name,
                    "type": "container"
                }
            }
            (state, data) = self.session.container_publish(container_snapshot,
                                                           instance)
            event_id = data.get('operation')
            self.session.wait_for_snapshot(event_id, instance)

            # Image has been create but the fingerprint is buried deep
            # in the metadata when the snapshot is complete
            (state, data) = self.session.operation_info(event_id, instance)
            fingerprint = data['metadata']['metadata']['fingerprint']
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Failed to publish snapshot for %(instance)s: '
                              '%(ex)s'), {'instance': instance.name,
                                          'ex': ex}, instance=instance)

        try:
            # Set the alias for the LXD image
            alias_config = {
                'name': image_id,
                'target': fingerprint
            }
            self.session.create_alias(alias_config, instance)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Failed to create alias for %(instance)s: '
                              '%(ex)s'), {'instance': instance.name,
                                          'ex': ex}, instance=instance)

        return fingerprint

    def _save_glance_image(self, context, instance, image_id, fingerprint):
        LOG.debug('_save_glance_image called for instance', instance=instance)

        try:
            snapshot = IMAGE_API.get(context, image_id)
            data = self.session.container_export(fingerprint, instance)
            image_meta = {'name': snapshot['name'],
                          'container_format': 'bare',
                          'disk_format': 'raw'}
            IMAGE_API.update(context, image_id, image_meta, data)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Failed to upload image to glance for '
                              '%(instance)s:  %(ex)s'),
                          {'instance': instance.name, 'ex': ex},
                          instance=instance)
