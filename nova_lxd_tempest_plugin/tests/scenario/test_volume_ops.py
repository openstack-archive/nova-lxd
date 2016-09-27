# Copyright 2013 NEC Corporation
# Copyright 2016 Canonical Ltd
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

import time

from oslo_log import log as logging
import testtools

from tempest.common.utils import data_utils
from tempest.common import waiters
from tempest import config
from tempest import exceptions
from tempest.lib.common.utils import test_utils
from tempest.lib import decorators
from tempest.lib import exceptions as lib_exc
from tempest.scenario import manager
from tempest import test

CONF = config.CONF
LOG = logging.getLogger(__name__)


class LXDVolumeScenario(manager.ScenarioTest):
    """The test suite for attaching volume to an instance

    The following is the scenario outline:
    1. Boot an instance "instance"
    2. Create a volume "volume1"
    3. Attach volume1 to instance
    4. Create a filesystem on volume1
    5. Mount volume1
    6. Create a file which timestamp is written in volume1
    7. Check for file on instnace1
    7. Unmount volume1
    8. Detach volume1 from instance1
    """

    def setUp(self):
        super(LXDVolumeScenario, self).setUp()
        self.image_ref = CONF.compute.image_ref
        self.flavor_ref = CONF.compute.flavor_ref
        self.run_ssh = CONF.validation.run_validation
        self.ssh_user = CONF.validation.image_ssh_user

    @classmethod
    def skip_checks(cls):
        super(LXDVolumeScenario, cls).skip_checks()

    def _wait_for_volume_available_on_the_system(self, ip_address,
                                                 private_key):
        ssh = self.get_remote_client(ip_address, private_key=private_key)

        def _func():
            part = ssh.get_partitions()
            LOG.debug("Partitions:%s" % part)
            return CONF.compute.volume_device_name in part

        if not test_utils.call_until_true(_func,
                                          CONF.compute.build_timeout,
                                          CONF.compute.build_interval):
            raise exceptions.TimeoutException

    def test_volume_attach(self):
        keypair = self.create_keypair()
        self.security_group = self._create_security_group()
        security_groups = [{'name': self.security_group['name']}]
        self.md = {'meta1': 'data1', 'meta2': 'data2', 'metaN': 'dataN'}
        server = self.create_server(
            image_id=self.image_ref,
            flavor=self.flavor_ref,
            key_name=keypair['name'],
            security_groups=security_groups,
            config_drive=CONF.compute_feature_enabled.config_drive,
            metadata=self.md,
            wait_until='ACTIVE')

        volume = self.create_volume()

        # create and add floating IP to server1
        ip_for_server = self.get_server_ip(server)

        self.nova_volume_attach(server, volume)
        self._wait_for_volume_available_on_the_system(ip_for_server,
                                                      keypair['private_key'])

        ssh_client = self.get_remote_client(
            ip_address=ip_for_server,
            username=self.ssh_user,
            private_key=keypair['private_key'])

        ssh_client.exec_command(
            'sudo /sbin/mke2fs -t ext4 /dev/%s'
            % CONF.compute.volume_device_name)
        ssh_client.exec_command(
            'sudo /bin/mount -t ext4 /dev/%s /mnt'
            % CONF.compute.volume_device_name)
        ssh_client.exec_command(
            'sudo sh -c "date > /mnt/timestamp; sync"')
        timestamp = ssh_client.exec_command(
            'test -f /mnt/timestamp && echo ok')
        ssh_client.exec_command(
            'sudo /bin/umount /mnt')

        self.nova_volume_detach(server, volume)
        self.assertEqual(u'ok\n', timestamp)
