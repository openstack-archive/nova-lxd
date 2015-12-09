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

from nova import i18n

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils

from nova_lxd.nova.virt.lxd import container_config
from nova_lxd.nova.virt.lxd import container_ops
from nova_lxd.nova.virt.lxd.session import session


_ = i18n._
_LE = i18n._LE
_LI = i18n._LI

CONF = cfg.CONF
LOG = logging.getLogger(__name__)


class LXDContainerMigrate(object):

    def __init__(self, virtapi):
        self.virtapi = virtapi
        self.config = container_config.LXDContainerConfig()
        self.session = session.LXDAPISession()
        self.container_ops = \
            container_ops.LXDContainerOperations(
                self.virtapi)

    def migrate_disk_and_power_off(self, context, instance, dest,
                                   flavor, network_info,
                                   block_device_info=None, timeout=0,
                                   retry_interval=0):
        LOG.debug("migrate_disk_and_power_off called", instance=instance)

        LOG.info(_('No disk to migrate'))

        # disk_info is not used
        disk_info = {}
        return disk_info

    def confirm_migration(self, migration, instance, network_info):
        LOG.debug("confirm_migration called", instance=instance)

    def finish_revert_migration(self, context, instance, network_info,
                                block_device_info=None, power_on=True):
        LOG.debug("finish_revert_migration called", instance=instance)
        container_config = self.get_container_config(instance)
        self.container_ops.start_container(container_config, instance,
                                           network_info,
                                           need_vif_plugged=True)

    def finish_migration(self, context, migration, instance, disk_info,
                         network_info, image_meta, resize_instance=False,
                         block_device_info=None, power_on=True):
        LOG.debug("finish_migration called", instance=instance)

        self._migration(migration, instance, network_info)

    def _migration(self, migration, instance, network_info):
        src_host = migration['source_compute']
        dst_host = migration['dest_compute']
        try:
            if self.session.container_defined(instance.name, instance):
                LOG.exception(_LE('Container already migrated'))
            self.session.container_stop(instance.name, src_host, instance)
            container_ws = self.session.container_migrate(
                instance.name, src_host, instance)
            container_config = (
                self.config.configure_container_migrate(
                    instance, container_ws, src_host))

            self.session.container_init(container_config,
                                        instance, dst_host)
            self.container_ops.start_container(container_config, instance,
                                               network_info,
                                               need_vif_plugged=True)
            self.session.container_destroy(instance.name, src_host, instance)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Failed to migrate container %(instance)s: '
                              '%(reason)s'),
                          {'instance': instance.name, 'reason': ex},
                          instance=instance)

    def live_migration(self, context, instance_ref, dest, post_method,
                       recover_method, block_migration=False,
                       migrate_data=None):
        LOG.debug("live_migration called", instance=instance_ref)
        post_method(context, instance_ref, dest, block_migration)

    def pre_live_migration(self, context, instance, block_device_info,
                           network_info):
        LOG.debug("pre_live_migration called", instance=instance)

    def post_live_migration(self, context, instance, block_device_info):
        LOG.debug("post_live_migration", instance=instance)
        pass

    def post_live_migration_at_destination(self, ctxt, instance_ref,
                                           network_info, block_migration,
                                           block_device_info):
        LOG.debug("post_live_migration_at_destination called",
                  instance=instance_ref)

    def check_can_live_migrate_destination(self, ctxt, instance_ref,
                                           src_compute_info, dst_compute_info,
                                           block_migration=False,
                                           disk_over_commit=False):
        LOG.debug("check_can_live_migrate_destination called", instance_ref)
        return {}

    def check_can_live_migrate_destination_cleanup(self, ctxt,
                                                   dest_check_data):
        LOG.debug("check_can_live_migrate_destination_cleanup called")

    def check_can_live_migrate_source(self, ctxt, instance_ref,
                                      dest_check_data):
        LOG.debug("check_can_live_migrate_source called", instance_ref)
        return dest_check_data
