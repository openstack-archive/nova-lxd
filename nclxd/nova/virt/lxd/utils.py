# Copyright (c) 2014 Canonical ltd
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

import grp
import getpass
import pwd
import os


from oslo.config import cfg
from nova.i18n import _

from nova.openstack.common import log as logging
from nova import context as nova_context
from nova import objects
from nova import utils

LOG = logging.getLogger(__name__)


CONF = cfg.CONF


def write_lxc_usernet(instance, bridge, user=None, count=1):
    if user is None:
        user = getpass.getuser()
    utils.execute('lxc-usernet-manage', 'set', user, bridge, str(count),
                  run_as_root=True, check_exit_code=[0])

def parse_subfile(name, fname):
    line = None
    with open(fname, "r") as fp:
        for cline in fp:
            if cline.startswith(name + ":"):
                line = cline
                break
        if line is None:
            raise ValueError("%s not found in %s" % (name, fname))
        toks = line.split(":")
    return (toks[1], toks[2])

def get_container_config(instance):
    return os.path.join(CONF.lxd.lxd_root_dir, instance['uuid'], 'config')


def get_container_rootfs(instance):
    return os.path.join(CONF.lxd.lxd_root_dir,instance['uuid'], 'rootfs')

def get_container_logfile(instance):
        return os.path.join(CONF.lxd.lxd_root_dir, instance['uuid'],
                        'container.logfile')

def get_container_console(instance):
    return os.path.join(CONF.lxd.lxd_root_dir, instance['uuid'],
                        'container.console')
