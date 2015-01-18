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
import grp
import pwd
import uuid

import lxc
import tarfile

from oslo.config import cfg
from oslo.utils import importutils, units

from nova.i18n import _, _LW, _LE, _LI
from nova.openstack.common import fileutils
from nova.openstack.common import log as logging
from nova import utils
from nova.virt import images
from nova import exception

from . import config
from . import image
from . import utils as container_utils
from . import vif

CONF = cfg.CONF
CONF.import_opt('use_cow_images', 'nova.virt.driver')
CONF.import_opt('vif_plugging_timeout', 'nova.virt.driver')
CONF.import_opt('vif_plugging_is_fatal', 'nova.virt.driver')
LOG = logging.getLogger(__name__)

MAX_CONSOLE_BYTES = 100 * units.Ki

def get_container_dir(instance):
    return os.path.join(CONF.lxd.lxd_root_dir, instance)

class Container(object):
    def __init__(self, client, virtapi, firewall):
        self.client = client
        self.virtapi = virtapi
        self.firewall_driver = firewall

        self.container = None
        self.image = None
        self.idmap = container_utils.LXCUserIdMap()
        self.vif_driver = vif.LXDGenericDriver()

        self.base_dir = os.path.join(CONF.lxd.lxd_root_dir,
                                     CONF.image_cache_subdirectory_name)

    def init_container(self):
        lxc_cgroup = uuid.uuid4()
        utils.execute('cgm', 'create', 'all', lxc_cgroup,
                      run_as_root=True)
        utils.execute('cgm', 'chown', 'all', lxc_cgroup,
                      pwd.getpwuid(os.getuid()).pw_uid,
                      pwd.getpwuid(os.getuid()).pw_gid,
                      run_as_root=True)
        utils.execute('cgm', 'movepid', 'all', lxc_cgroup, os.getpid())

    def get_console_log(self, instance):
        console_log = os.path.join(CONF.lxd.lxd_root_dir,
                                   instance['uuid'],
                                   'console.log')
        with open(console_log, 'rb') as fp:
            log_data, remaining = utils.last_bytes(fp, MAX_CONSOLE_BYTES)
            if remaining > 0:
                LOG.info(_LI('Truncated console log returned, '
                             '%d bytes ignored'),
                         remaining, instance=instance)
        return log_data

    def start_container(self, context, instance, image_meta, injected_files,
			admin_password, network_info, block_device_info, flavor):
        LOG.info(_LI('Starting new instance'), instance=instance)

        self.container = lxc.Container(instance['uuid'])
        self.container.set_config_path(CONF.lxd.lxd_root_dir)

        ''' Create the instance directories '''
        self._create_container(instance['uuid'])

        ''' Fetch the image from glance '''
        self._fetch_image(context, instance)

        ''' Start the contianer '''
        self._start_container(context, instance, network_info, image_meta)

    def _create_container(self, instance):
        if not os.path.exists(get_container_dir(instance)):
            fileutils.ensure_tree(get_container_dir(instance))
        if not os.path.exists(self.base_dir):
            fileutils.ensure_tree(self.base_dir)

    def _fetch_image(self, context, instance):
        container_image = os.path.join(self.base_dir, '%s.tar.gz' % instance['image_ref'])

        if not os.path.exists(container_image):
            root_dir = os.path.join(root_dir, 'rootfs')
            images.fetch_to_raw(context, instance['image_ref'], container_image,
                                instance['user_id'], instance['project_id'])
            if not tarfile.is_tarfile(container_image):
                raise exception.NovaException(_('Not an valid image'))

        if CONF.use_cow_images:
            root_dir = os.path.join(get_container_dir(instance['uuid']), 'rootfs')
            self.image = image.ContainerCoW(container_image, instance, root_dir, self.base_dir)
        else:
            root_dir = fileutils.ensure_tree(os.path.join(get_container_dir(instance['uuid']),
                                            'rootfs'))
            self.image = image.ContainerLocal(container_image, instance, root_dir)

        self.image.create_container()

    def _start_container(self, context, instance, network_info, image_meta):
        timeout = CONF.vif_plugging_timeout
        # check to see if neutron is ready before
        # doing anything else
        if (not self.client.running(instance['uuid']) and
                utils.is_neutron() and timeout):
            events = self._get_neutron_events(network_info)
        else:
            events = {}

        try:
            with self.virtapi.wait_for_instance_event(
                    instance, events, deadline=timeout,
                    error_callback=self._neutron_failed_callback):
                self._write_config(instance, network_info, image_meta)
                self._start_network(instance, network_info)
                self._start_firewall(instance, network_info)
                self.client.start(instance['uuid'])
        except exception.VirtualInterfaceCreateException:
            LOG.info(_LW('Failed'))

    def _write_config(self, instance, network_info, image_meta):
        template = config.LXDConfigTemplate(instance['uuid'], image_meta)
        template.set_config()

        self.container.load_config()

        name = config.LXDConfigSetName(self.container, instance['uuid'])
        name.set_config()

        rootfs = config.LXDConfigSetRoot(self.container, instance['uuid'])
        rootfs.set_config()

        logpath = config.LXDConfigSetLog(self.container, instance['uuid'])
        logpath.set_config()

        console_log = config.LXDConfigConsole(self.container, instance['uuid'])
        console_log.set_config()

        idmap = config.LXDUserConfig(self.container, self.idmap)
        idmap.set_config()

        limit = config.LXDSetLimits(self.container, instance)
        limit.set_config()

        self.container.save_config()

    def _start_network(self, instance, network_info):
        for vif in network_info:
            self.vif_driver.plug(instance, vif)

    def teardown_network(self, instance, network_info):
        for vif in network_info:
            self.vif_driver.unplug(instance, vif)
        self._stop_firewall(instance, network_info)

    def _start_firewall(self, instance, network_info):
        self.firewall_driver.setup_basic_filtering(instance, network_info)
        self.firewall_driver.prepare_instance_filter(instance, network_info)
        self.firewall_driver.apply_instance_filter(instance, network_info)

    def _stop_firewall(self, instance, network_info):
        self.firewall_driver.unfilter_instance(instance, network_info)

    def _get_neutron_events(self, network_info):
        return [('network-vif-plugged', vif['id'])
                for vif in network_info if vif.get('active', True) is False]

    def _neutron_failed_callback(self, event_name, instance):
        LOG.error(_LE('Neutron Reported failure on event '
                      '%(event)s for instance %(uuid)s'),
                    {'event': event_name, 'uuid': instance.uuid})
        if CONF.vif_plugging_is_fatal:
            raise exception.VirtualInterfaceCreateException()
