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

from nova import utils

from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_log import log as logging
import six

CONF = cfg.CONF
LOG = logging.getLogger(__name__)


def mount_filesystem(self, dev_path, dir_path):
    try:
        _out, err = utils.execute('mount',
                                  '-t', 'ext4',
                                  dev_path, dir_path, run_as_root=True)
    except processutils.ProcessExecutionError as e:
        err = six.text_type(e)
    return err


def umount_filesystem(self, dir_path):
    try:
        _out, err = utils.execute('umount',
                                  dir_path, run_as_root=True)
    except processutils.ProcessExecutionError as e:
        err = six.text_type(e)
    return err
