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

from nova.i18n import _


class Migration(object):
    def __init__(self):
        pass

    def migrate_disk_and_power_off(self, context, instance, dest,
                                   flavor, network_info,
                                   block_device_info=None,
                                   timeout=0, retry_interval=0):
        raise NotImplementedError()

    def finish_migration(self, context, migration, instance, disk_info,
                         network_info, image_meta, resize_instance,
                         block_device_info=None, power_on=True):
        raise NotImplementedError()

    def confirm_migration(self, migration, instance, network_info):
        """Confirms a resize, destroying the source VM.

        :param instance: nova.objects.instance.Instance
        """
        # TODO(Vek): Need to pass context in for access to auth_token
        raise NotImplementedError()

    def finish_revert_migration(self, context, instance, network_info,
                                block_device_info=None, power_on=True):
        raise NotImplementedError()

    def pre_live_migration(self, context, instance, block_device_info,
                           network_info, disk_info, migrate_data=None):
        raise NotImplementedError()

    def live_migration(self, context, instance, dest,
                       post_method, recover_method, block_migration=False,
                       migrate_data=None):
        raise NotImplementedError()

    def rollback_live_migration_at_destination(self, context, instance,
                                               network_info,
                                               block_device_info,
                                               destroy_disks=True,
                                               migrate_data=None):
        raise NotImplementedError()

    def post_live_migration(self, context, instance, block_device_info,
                            migrate_data=None):
        pass

    def post_live_migration_at_source(self, context, instance, network_info):
        raise NotImplementedError(_("Hypervisor driver does not support "
                                    "post_live_migration_at_source method"))

    def post_live_migration_at_destination(self, context, instance,
                                           network_info,
                                           block_migration=False,
                                           block_device_info=None):
        raise NotImplementedError()

    def check_can_live_migrate_destination(self, context, instance,
                                           src_compute_info, dst_compute_info,
                                           block_migration=False,
                                           disk_over_commit=False):
        raise NotImplementedError()

    def check_can_live_migrate_destination_cleanup(self, context,
                                                   dest_check_data):
        raise NotImplementedError()

    def check_can_live_migrate_source(self, context, instance,
                                      dest_check_data, block_device_info=None):
        raise NotImplementedError()
