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

import ddt
import mock


class MockConf(mock.Mock):

    def __init__(self, lxd_args=(), lxd_kwargs={}, *args, **kwargs):
        default = {
            'config_drive_format': None,
            'instances_path': '/fake/instances/path',
            'image_cache_subdirectory_name': '/fake/image/cache',
        }
        default.update(kwargs)
        super(MockConf, self).__init__(*args, **default)

        lxd_default = {
            'lxd_default_profile': 'fake_profile',
            'lxd_root_dir': '/fake/lxd/root',
        }
        lxd_default.update(lxd_kwargs)
        self.lxd = mock.Mock(lxd_args, **lxd_default)


class MockInstance(mock.Mock):

    def __init__(self, name='mock_instance', image_ref='mock_image',
                 ephemeral_gb=0, memory_mb=-1, vcpus=0, *args, **kwargs):
        super(MockInstance, self).__init__(
            image_ref=image_ref,
            ephemeral_gb=ephemeral_gb,
            *args, **kwargs)
        self.name = name
        self.flavor = mock.Mock(memory_mb=memory_mb, vcpus=vcpus)


def lxd_mock(*args, **kwargs):
    default = {
        'profile_list.return_value': ['fake_profile'],
        'container_list.return_value': ['mock-instance-1', 'mock-instance-2'],
        'host_ping.return_value': True,
    }
    default.update(kwargs)
    return mock.Mock(*args, **default)


def annotated_data(*args):
    class List(list):
        pass

    new_args = []

    for arg in args:
        new_arg = List(arg)
        new_arg.__name__ = arg[0]
        new_args.append(new_arg)

    return lambda func: ddt.data(*new_args)(ddt.unpack(func))
