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
from nova.i18n import _LW

from nova.openstack.common import log as logging
from nova.openstack.common import fileutils
from nova import utils

CONF = cfg.CONF
LOG = logging.getLogger(__name__)


class LXDConfigObject(object):

    def __init__(self, **kwargs):
        super(LXDConfigObject, self).__init__()

    def set_config(self):
        pass


class LXDConfigTemplate(LXDConfigObject):

    def __init__(self, instance, image_meta):
        super(LXDConfigTemplate, self).__init__()
        self.instance = instance
        self.image_meta = image_meta

    def set_config(self):
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
            config_file = os.path.join(CONF.lxd.lxd_root_dir,
                                       self.instance, 'config')

            f = open(config_file, 'w')
            f.write('lxc.include = %s/%s.common.conf\n'
                    % (CONF.lxd.lxd_config_dir,
                       lxc_template))
            f.write('lxc.include = %s/%s.userns.conf\n'
                    % (CONF.lxd.lxd_config_dir,
                       lxc_template))


class LXDConfigSetName(LXDConfigObject):

    def __init__(self, container, instance):
        super(LXDConfigSetName, self).__init__()
        self.container = container
        self.instance = instance

    def set_config(self):
        self.container.append_config_item('lxc.utsname',
                                          self.instance)


class LXDConfigSetRoot(LXDConfigObject):

    def __init__(self, container, instance):
        super(LXDConfigSetRoot, self).__init__()
        self.container = container
        self.instance = instance
        self.container_rootfs = os.path.join(CONF.lxd.lxd_root_dir,
                                             self.instance,
                                             'rootfs')

    def set_config(self):
        self.container.append_config_item('lxc.rootfs',
                                          self.container_rootfs)


class LXDConfigSetLog(LXDConfigObject):

    def __init__(self, container, instance):
        super(LXDConfigSetLog, self).__init__()
        self.container = container
        self.instance = instance

    def set_config(self):
        container_logfile = os.path.join(CONF.lxd.lxd_root_dir,
                                         self.instance,
                                         'logfile')
        self.container.append_config_item('lxc.logfile',
                                          container_logfile)


class LXDConfigConsole(LXDConfigObject):

    def __init__(self, container, instance):
        super(LXDConfigConsole, self).__init__()
        self.container = container
        self.instance = instance

    def set_config(self):
        console_log = os.path.join(CONF.lxd.lxd_root_dir,
                                   self.instance,
                                   'console.log')
        self.container.append_config_item('lxc.console.logfile',
                                          console_log)
        utils.execute('touch', console_log)


class LXDUserConfig(LXDConfigObject):

    def __init__(self, container, idmap):
        super(LXDUserConfig, self).__init__()
        self.container = container
        self.idmap = idmap

    def set_config(self):
        for ent in self.idmap.lxc_conf_lines():
            self.container.append_config_item(*ent)


class LXDSetLimits(LXDConfigObject):

    def __init__(self, container, instance):
        super(LXDSetLimits, self).__init__()
        self.container = container
        self.instance = instance

    def set_config(self):
        flavor = self.instance.get_flavor()
        self.container.append_config_item(
            'lxc.cgroup.memory.limit_in_bytes',
            '%sM' % flavor.memory_mb)

class LXDSetNetwork(LXDConfigObject):

    def __init__(self, container, network):
        super(LXDSetNetwork, self).__init__()
        self.container = container
        self.network = network

    def set_config(self):
        for vif in self.network:
            self.container.append_config_item(
                'lxc.network.type', 'veth'
            )
            self.container.append_config_item(
                'lxc.network.hwaddr',
                vif['address']
            )
            if vif['type'] == 'ovs':
                bridge = 'qbr%s' % vif['id'][:11]
            else:
                bridge = vif['network']['bridge']
            self.container.append_config_item(
                'lxc.network.link',
                bridge
            )