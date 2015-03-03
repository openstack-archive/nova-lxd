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

import copy
import os


from oslo.config import cfg
from oslo_log import log as logging

CONF = cfg.CONF
LOG = logging.getLogger(__name__)

def get_container_console(instance):
    return os.path.join(CONF.lxd.lxd_root_dir, instance['uuid'],
                        'container.console')

class LXDSetConfig(object):
    def __init__(self, config, instance, image_meta, network_info):
        self.instance = instance
        self.config = config
        self.image_meta = image_meta
        self.network_info = network_info

        self.image = {}
        self.raw_lxc = {}

    def write_config(self):
        self._get_lxd_config()
        self.config['config'] = self.raw_lxc
        self.config['source'] = self.image

        return self.config

    def _get_lxd_config(self):
        # Specify the console
        console_log = 'lxc.console.logfile = %s\n' % get_container_console(self.instance)
        self.raw_lxc['lxc.raw'] = console_log

        # Specify the network
        for vif in self.network_info:
            vif_id = vif['id'][:11]
            vif_type = vif['type']
            bridge = vif['network']['bridge']
            mac = vif['address']

            if vif_type == 'ovs':
                bridge = 'qbr%s' % vif_id

            self.raw_lxc['lxc.raw'] += 'lxc.network.type = veth\n'
            self.raw_lxc['lxc.raw'] += 'lxc.network.addr = %s\n' % mac
            self.raw_lxc['lxc.raw'] += 'lxc.network.link = %s\n' % bridge

        self.image = {'type': 'image', 'alias': self.instance['image_ref']}
