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

from nova import utils
from nova.i18n import _, _LW, _LE, _LI
from nova.openstack.common import log as logging

from . import utils as container_utils

LOG = logging.getLogger(__name__)


def write_image(idmap, image, root_dir):
    tar = ['tar', '--directory', root_dir,
           '--anchored', '--numeric-owner', '-xpzf', image]
    nsexec = (['lxc-usernsexec'] +
              idmap.usernsexec_margs(with_read="user") +
              ['--'])
    args = tuple(nsexec + tar)
    utils.execute(*args, check_exit_code=[0, 2])


class ContainerImage(object):

    def __init__(self, **kwargs):
        super(ContainerImage, self).__init__()

    def create_container(self):
        pass

    def remove_contianer(self):
        pass


class ContainerLocal(ContainerImage):

    def __init__(self, image, instance, root_dir):
        super(ContainerLocal, self).__init__()
        self.image = image
        self.instance = instance
        self.root_dir = root_dir

        self.idmap = container_utils.LXCUserIdMap()

    def create_container(self):
        (user, group) = self.idmap.get_user()
        utils.execute('chown', '%s:%s' % (user, group), self.root_dir,
                      run_as_root=True)
        write_image(self.idmap, self.image, self.root_dir)

    def remove_container(self):
        pass


class ContainerCoW(ContainerImage):

    def __init__(self, image, instance, root_dir, base_dir):
        super(ContainerCoW, self).__init__()
        self.idmap = container_utils.LXCUserIdMap()
        self.image = image
        self.instance = instance
        self.root_dir = root_dir
        self.base_dir = base_dir

    def create_container(self):
        image_dir = os.path.join(self.base_dir, self.instance['image_ref'])
        LOG.info(_LI('!!! %s') % image_dir)
        if not os.path.exists(image_dir):
            (user, group) = self.idmap.get_user()
            utils.execute('btrfs', 'subvolume', 'create', image_dir)
            utils.execute('chown', '%s:%s' % (user, group), image_dir,
                          run_as_root=True)
            write_image(self.idmap, self.image,  image_dir)

        utils.execute('btrfs', 'subvolume', 'snapshot', image_dir,
                      self.root_dir, run_as_root=True)
        size = self.instance['root_gb']
        if size != 0:
            utils.execute('btrfs', 'quota', 'enable', self.root_dir,
                          run_as_root=True)
            utils.execute('btrfs', 'qgroup', 'limit', '%sG' % size,
                          self.root_dir, run_as_root=True)

    def remove_container(self):
        pass
