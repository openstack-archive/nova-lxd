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
import nova.conf
from nova import i18n

from oslo_log import log as logging
from oslo_utils import excutils

from nova.virt.lxd import session
from nova.virt.lxd import vif as lxd_vif
from nova.virt import firewall

_ = i18n._
_LE = i18n._LE
_LI = i18n._LI

CONF = nova.conf.CONF
LOG = logging.getLogger(__name__)


class LXDContainerMigrate(object):

    def __init__(self, driver):
        self.driver = driver

        self.vif_driver = lxd_vif.LXDGenericDriver()
        self.firewall_driver = firewall.load_driver(
            default='nova.virt.firewall.NoopFirewallDriver')

        self.session = session.LXDAPISession()

    #
    # live-migration
    #

    def pre_live_migration(self, context, instance, block_device_info,
                           network_info, disk_info, migrate_data=None):
        LOG.debug('pre_live_migration called for instance', instance=instance)
        try:
            for vif in network_info:
                self.vif_driver.plug(instance, vif)
            self.firewall_driver.setup_basic_filtering(
                instance, network_info)
            self.firewall_driver.prepare_instance_filter(
                instance, network_info)
            self.firewall_driver.apply_instance_filter(
                instance, network_info)

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
            self._container_init(dest, instance)
            post_method(context, instance, dest, block_migration)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('live_migration failed for %(instance)s: '
                              '%(reason)s'),
                          {'instance': instance.name, 'reason': ex},
                          instance=instance)

    def _copy_container_profile(self, instance, network_info):
        LOG.debug('_copy_cotontainer_profile called for instnace',
                  instance=instance)
        container_profile = self.driver.create_profile(instance,
                                                       network_info)
        self.session.profile_create(container_profile, instance)

    def _container_init(self, host, instance):
        LOG.debug('_container_init called for instnace', instance=instance)

        (state, data) = (self.session.container_migrate(instance.name,
                                                        CONF.my_ip,
                                                        instance))
        container_config = {
            'name': instance.name,
            'profiles': [instance.name],
            'source': self.driver.get_container_migrate(
                data, host, instance)
        }
        self.session.container_init(container_config, instance, host)
