# Copyright 2016 Canonical Ltd
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

import os

import nova.conf
from nova import exception
from nova import i18n
from nova.objects import migrate_data as migrate_data_obj
from nova.virt import configdrive

from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import fileutils

from nova.virt.lxd import config
from nova.virt.lxd import operations
from nova.virt.lxd import utils as container_dir
from nova.virt.lxd import session


_ = i18n._
_LE = i18n._LE
_LI = i18n._LI

CONF = nova.conf.CONF
LOG = logging.getLogger(__name__)


class LXDContainerMigrate(object):

    def __init__(self, virtapi):
        self.virtapi = virtapi
        self.config = config.LXDContainerConfig()
        self.container_dir = container_dir.LXDContainerDirectories()
        self.session = session.LXDAPISession()
        self.operations = \
            operations.LXDContainerOperations(
                self.virtapi)

    #
    # migrate/resize
    #

    def migrate_disk_and_power_off(self, context, instance, dest,
                                   flavor, network_info,
                                   block_device_info=None, timeout=0,
                                   retry_interval=0):
        LOG.debug("migrate_disk_and_power_off called", instance=instance)

        same_host = False
        if CONF.my_ip == dest:
            same_host = True
            LOG.debug('Migration target is the source host')
        else:
            LOG.debug('Migration target host: %s' % dest)

        if not self.session.container_defined(instance.name, instance):
            msg = _('Instance is not found.')
            raise exception.NovaException(msg)

        try:
            if same_host:
                container_profile = self.config.create_profile(instance,
                                                               network_info)
                self.session.profile_update(container_profile, instance)
            else:
                self.session.container_stop(instance.name, instance)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('failed to resize container '
                              '%(instance)s: %(ex)s'),
                          {'instance': instance.name, 'ex': ex},
                          instance=instance)

        # disk_info is not used
        return ""

    def confirm_migration(self, migration, instance, network_info):
        LOG.debug("confirm_migration called", instance=instance)

        if not self.session.container_defined(instance.name, instance):
            msg = _('Failed to find container %(instance)s') % \
                {'instance': instance.name}
            raise exception.NovaException(msg)

        try:
            self.session.profile_delete(instance)
            self.session.container_destroy(instance.name,
                                           instance)
            self.operations.unplug_vifs(instance, network_info)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.exception(_LE('Confirm migration failed for %(instance)s: '
                                  '%(ex)s'), {'instance': instance.name,
                                              'ex': ex}, instance=instance)

    def finish_migration(self, context, migration, instance, disk_info,
                         network_info, image_meta, resize_instance=False,
                         block_device_info=None, power_on=True):
        LOG.debug("finish_migration called", instance=instance)

        if self.session.container_defined(instance.name, instance):
            return

        try:
            # Ensure that the instance directory exists
            instance_dir = \
                self.container_dir.get_instance_dir(instance.name)
            if not os.path.exists(instance_dir):
                fileutils.ensure_tree(instance_dir)

            if configdrive.required_by(instance):
                configdrive_dir = \
                    self.container_dir.get_container_configdrive(
                        instance.name)
                fileutils.ensure_tree(configdrive_dir)

            # Step 1 - Setup the profile on the dest host
            self._copy_container_profile(instance, network_info)

            # Step 2 - Open a websocket on the srct and and
            #          generate the container config
            self._container_init(migration['source_compute'], instance)

            # Step 3 - Start the network and contianer
            self.operations.plug_vifs(instance, network_info)
            self.session.container_start(instance.name, instance)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.exception(_LE('Migration failed for %(instance)s: '
                                  '%(ex)s'),
                              {'instance': instance.name,
                               'ex': ex}, instance=instance)

    def finish_revert_migration(self, context, instance, network_info,
                                block_device_info=None, power_on=True):
        LOG.debug('finish_revert_migration called for instance',
                  instance=instance)
        if self.session.container_defined(instance.name, instance):
            self.session.container_start(instance.name, instance)

    #
    # live-migration
    #

    def pre_live_migration(self, context, instance, block_device_info,
                           network_info, disk_info, migrate_data=None):
        LOG.debug('pre_live_migration called for instance', instance=instance)
        try:
            self._copy_container_profile(instance, network_info)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('pre_live_migration failed for %(instance)s: '
                              '%(reason)s'),
                          {'instance': instance.name, 'reason': ex},
                          instance=instance)

    def live_migration(self, context, instance, dest,
                       post_method, recover_method, block_migration=False,
                       migrate_data=None):
        LOG.debug('live_migration called for instance', instance=instance)
        try:
            self._container_init(CONF.my_ip, instance)
            post_method(context, instance, dest, block_migration, host=dest)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('live_migration failed for %(instance)s: '
                              '%(reason)s'),
                          {'instance': instance.name, 'reason': ex},
                          instance=instance)

    def post_live_migration(self, context, instance, block_device_info,
                            migrate_data=None):
        LOG.debug('post_live_migration called for instance',
                  instance=instance)
        try:
            self.session.container_destroy(instance.name, instance)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('post_live_migration failed for %(instance)s: '
                              '%(reason)s'),
                          {'instance': instance.name, 'reason': ex},
                          instance=instance)

    def post_live_migration_at_destination(self, context, instance,
                                           network_info,
                                           block_migration=False,
                                           block_device_info=None):
        LOG.debug('post_live_migration_at_destinaation called for instance',
                  instance=instance)
        return

    def post_live_migration_at_source(self, context, instance, network_info):
        LOG.debug('post_live_migration_at_source called for instance',
                  instance=instance)
        try:
            self.operations.cleanup(context, instance, network_info)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('post_live_migration failed for %(instance)s: '
                              '%(reason)s'),
                          {'instance': instance.name, 'reason': ex},
                          instance=instance)

    def check_can_live_migrate_destination(self, context, instance,
                                           src_compute_info, dst_compute_info,
                                           block_migration=False,
                                           disk_over_commit=False):
        LOG.debug('check_can_live_migration called for instance',
                  instance=instance)
        if self.session.container_defined(instance.name, instance):
            raise exception.InstanceExists(name=instance.name)

        # XXX (zulcss) - June 14, 2016 - Workaround
        # for LXD sending an empty migrate object
        # that descirbes the host that the instance
        # is being migrated to. Replace the
        # HyperVLiveMigrateData object with an
        # LXD named object.
        return migrate_data_obj.HyperVLiveMigrateData()

    def check_can_live_migrate_destination_cleanup(self, context,
                                                   dest_check_data):
        LOG.debug('check_can_live_migrate_destination_cleanup')
        return

    def check_can_live_migrate_source(self, context, instance,
                                      dest_check_data,
                                      block_device_info=None):
        LOG.debug('check_can_live_migrate_source called for instance',
                  instance=instance)

        if not CONF.lxd.allow_live_migrate:
            msg = (_('Live migration is a en experimental feature'
                     ' of LXD and is still in heavy development.'))
            LOG.error(msg, instance=instance)
            raise exception.MigrationPreCheckError(reason=msg)

        return dest_check_data

    def _copy_container_profile(self, instance, network_info):
        LOG.debug('_copy_cotontainer_profile called for instnace',
                  instance=instance)
        container_profile = self.config.create_profile(instance,
                                                       network_info)
        self.session.profile_create(container_profile, instance)

    def _container_init(self, host, instance):
        LOG.debug('_container_init called for instnace', instance=instance)

        (state, data) = (self.session.container_migrate(instance.name,
                                                        CONF.my_ip,
                                                        instance))
        container_config = self.config.create_container(instance)
        container_config['source'] = \
            self.config.get_container_migrate(data, host, instance)
        self.session.container_init(container_config, instance, host)
