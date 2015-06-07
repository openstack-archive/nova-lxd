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

import os

from oslo_config import cfg
from oslo_log import log as logging

from nova.i18n import _LE
from nova.virt import images


CONF = cfg.CONF
LOG = logging.getLogger(__name__)


def get_base_dir():
    return os.path.join(CONF.instances_path,
                        CONF.image_cache_subdirectory_name)


def get_container_image(instance):
    base_dir = get_base_dir()
    return os.path.join(base_dir,
                        '%s.tar.gz' % instance.image_ref)


def fetch_image(context, image, instance, max_size=0):
    try:
        images.fetch(context, instance.image_ref, image,
                     instance.user_id, instance.project_id,
                     max_size=max_size)
    except Exception:
        LOG.exception(_LE("Image %(image_id)s doesn't exist anymore on"),
                              {'image_id': instance.image_ref})

def get_console_path(instance):
    return os.path.join(CONF.lxd.lxd_root_dir,
                        'lxc',
                        instance.uuid,
                        'console.log')

def get_container_dir(instance):
    return os.path.join(CONF.lxd.lxd_root_dir,
                        'lxc',
                        instance.uuid)

