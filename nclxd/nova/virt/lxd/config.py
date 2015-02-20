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

import jinja2

from oslo.config import cfg
from nova.i18n import _LW, _

from nova import exception
from nova import utils

from . import utils as container_utils

from nova.openstack.common import log as logging

CONF = cfg.CONF
LOG = logging.getLogger(__name__)


class LXDSetConfig(object):
    def __init__(self, container, instance, image_meta, network_info):
        self.container = container
        self.instance = instance
        self.image_meta = image_meta
        self.network_info = network_info

        self.config = {}

    def write_config(self):
        lxc_template = self.get_lxd_template()
        if lxc_template:
            net = self.config_lxd_network()
            (user, uoffset) = container_utils.parse_subfile(CONF.lxd.lxd_default_user,
                                                            '/etc/sbuid')
            (group, goffset) = container_utils.parse_subfile(CONF.lxd.lxd_default_user,
                                                             '/etc/subgid')
            self.config = {
                'lxd_common_config': '%s/%s.common.conf' % (CONF.lxd.lxd_config_dir,
                                                                       lxc_template),
                'lxd_userns_config': '%s/%s.userns.conf' % (CONF.lxd.lxd_config_dir,
                                                            lxc_template),
                'lxd_rootfs': self.config_lxd_rootfs(),
                'lxd_name': self.config_lxd_name(),
                'lxd_logfile': self.config_lxd_logging(),
                'lxd_console_file': self.config_lxd_console(),
                'lxd_mac_addr': net['mac'],
                'lxd_network_link': net['link'],
                'lxd_user': user,
                'lxd_uoffset': uoffset,
                'lxd_group': group,
                'lxd_goffset': goffset
            }

        tmpl_path, tmpl_file = os.path.split(CONF.lxd.lxd_config_template)
        env = jinja2.Environment(loader=jinja2.FileSystemLoader(tmpl_path),
                                 trim_blocks=True)
        template = env.get_template(tmpl_file)
        tmpl = template.render(self.config)
        config_file = container_utils.get_container_config(self.instance)
        f = open(config_file, 'w')
        f.write(tmpl)
        f.close()

    def config_lxd_name(self):
        if self.instance:
            return self.instance['uuid']

    def config_lxd_rootfs(self):
        container_rootfs = container_utils.get_container_rootfs(self.instance)
        if not os.path.exists(container_rootfs):
            msg = _('Container rootfs not found')
            raise exception.InstanceNotReady(msg)

        return container_rootfs

    def config_lxd_logging(self):
        return container_utils.get_container_logfile(self.instance)

    def config_lxd_network(self):
        net = {}
        if self.network_info:
            # NOTE(jamespage) this does not deal with multiple nics.
            for vif in self.network_info:
                vif_id = vif['id'][:11]
                vif_type = vif['type']
                bridge = vif['network']['bridge']
                mac = vif['address']

            if vif_type == 'ovs':
                bridge = 'qbr%s' % vif_id

            net = {'mac': mac,
                   'link': bridge}
        return net

    def config_lxd_console(self):
        return container_utils.get_container_console(self.instance)

    def config_lxd_limits(self):
        pass

    def get_lxd_template(self):
        LOG.debug('Fetching LXC template')

        templates = []
        if (self.image_meta and
                self.image_meta.get('properties', {}).get('template')):
            lxc_template = self.image_meta['properties'].get('template')
        else:
            lxc_template = CONF.lxd.lxd_default_template
        path = os.listdir(CONF.lxd.lxd_template_dir)
        for line in path:
            templates.append(line.replace('lxc-', ''))
        if lxc_template in templates:
            return lxc_template