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

from oslo.config import cfg
from nova.i18n import _LW, _

from nova import exception
from nova import utils


from nova.openstack.common import log as logging

CONF = cfg.CONF
LOG = logging.getLogger(__name__)


class LXDSetConfig(object):
    def __init__(self, container, instance, idmap, image_meta, network_info):
        self.container = container
        self.instance = instance
        self.idmap = idmap
        self.image_meta = image_meta
        self.network_info = network_info

        self.config = {}

    def write_config(self):
        lxc_template = self._get_lxc_template()
        if lxc_template:
            self._write_lxc_template(lxc_template)
            self.container.load_config()
            self.config_lxc_name()
            self.config_lxc_rootfs()
            self.config_lxc_user()
            self.config_lxc_logging()
            self.config_lxc_network()
            self.config_lxc_console()
            self.config_lxc_limits()
            self.container.save_config()

    def config_lxc_name(self):
        if self.instance:
            self.container.append_config_item('lxc.utsname',
                                 self.instance['uuid'])

    def config_lxc_rootfs(self):
        container_rootfs = self._get_container_rootfs()
        if not os.path.exists(container_rootfs):
            msg = _('Container rootfs not found')
            raise exception.InstanceNotReady(msg)

        self.container.append_config_item('lxc.rootfs', container_rootfs)

    def config_lxc_logging(self):
        self.container.append_config_item(
            'container.logfile',
            self._get_container_logfile()
        )

    def config_lxc_network(self):
        if self.network_info:
            # NOTE(jamespage) this does not deal with multiple nics.
            for vif in self.network_info:
                vif_id = vif['id'][:11]
                vif_type = vif['type']
                bridge = vif['network']['bridge']
                mac = vif['address']

            if vif_type == 'ovs':
                bridge = 'qbr%s' % vif_id

            self.container.append_config_item('lxc.network.type', 'veth')
            self.container.append_config_item('lxc.network.hwaddr', mac)
            self.container.append_config_item('lxc.network.link', bridge)

    def config_lxc_console(self):
        self.container.append_config_item(
            'container.console',
            self._get_container_console()
        )


    def config_lxc_limits(self):
        pass

    def config_lxc_user(self):
        for ent in self.idmap.lxc_conf_lines():
           self.container.append_config_item(*ent)

    def _get_lxc_template(self):
        LOG.debug('Fetching LXC template')

        templates = []
        if (self.image_meta and
                self.image_meta.get('properties', {}).get('template')):
            lxc_template = self.image_meta['propeties'].get('template')
        else:
            lxc_template = CONF.lxd.lxd_default_template
        path = os.listdir(CONF.lxd.lxd_template_dir)
        for line in path:
            templates.append(line.replace('lxc-', ''))
        if lxc_template in templates:
            return lxc_template

    def _write_lxc_template(self, template_name):
        config_file = self._get_container_config()
        f = open(config_file, 'w')
        f.write('lxc.include = %s/%s.common.conf\n' % (CONF.lxd.lxd_config_dir,
                                                       template_name))
        f.write('lxc.include = %s/%s.userns.conf\n' % (CONF.lxd.lxd_config_dir,
                                                       template_name))
        f.close()

    def _get_container_config(self):
        return os.path.join(CONF.lxd.lxd_root_dir, self.instance['uuid'], 'config')


    def _get_container_rootfs(self):
        return os.path.join(CONF.lxd.lxd_root_dir, self.instance['uuid'], 'rootfs')

    def _get_container_logfile(self):
        return os.path.join(CONF.lxd.lxd_root_dir, self.instance['uuid'],
                        'container.logfile')

    def _get_container_console(self):
        return os.path.join(CONF.lxd.lxd_root_dir, self.instance['uuid'],
                        'container.console'])