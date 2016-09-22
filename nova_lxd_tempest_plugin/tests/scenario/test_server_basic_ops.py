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

import json
import re

from tempest import config
from tempest import exceptions
from tempest.lib.common.utils import test_utils
from tempest.scenario import manager
from tempest import test

CONF = config.CONF


class TestServerBasicOps(manager.ScenarioTest):

    """The test suite for server basic operations

    This smoke test case follows this basic set of operations:
     * Create a keypair for use in launching an instance
     * Create a security group to control network access in instance
     * Add simple permissive rules to the security group
     * Launch an instance
     * Perform ssh to instance
     * Verify metadata service
     * Terminate the instance
    """

    def setUp(self):
        super(TestServerBasicOps, self).setUp()
        self.image_ref = CONF.compute.image_ref
        self.flavor_ref = CONF.compute.flavor_ref
        self.run_ssh = CONF.validation.run_validation
        self.ssh_user = CONF.validation.image_ssh_user

    def verify_ssh(self, keypair):
        if self.run_ssh:
            # Obtain a floating IP
            self.fip = self.create_floating_ip(self.instance)['ip']
            # Check ssh
            self.ssh_client = self.get_remote_client(
                ip_address=self.fip,
                username=self.ssh_user,
                private_key=keypair['private_key'])

    def verify_metadata(self):
        if self.run_ssh and CONF.compute_feature_enabled.metadata_service:
            # Verify metadata service
            md_url = 'http://169.254.169.254/latest/meta-data/public-ipv4'

            def exec_cmd_and_verify_output():
                cmd = 'curl ' + md_url
                result = self.ssh_client.exec_command(cmd)
                if result:
                    msg = ('Failed while verifying metadata on server. Result '
                           'of command "%s" is NOT "%s".' % (cmd, self.fip))
                    self.assertEqual(self.fip, result, msg)
                    return 'Verification is successful!'

            if not test_utils.call_until_true(exec_cmd_and_verify_output,
                                              CONF.compute.build_timeout,
                                              CONF.compute.build_interval):
                raise exceptions.TimeoutException('Timed out while waiting to '
                                                  'verify metadata on server. '
                                                  '%s is empty.' % md_url)

    @test.attr(type='smoke')
    @test.services('compute', 'network')
    def test_server_basic_ops(self):
        keypair = self.create_keypair()
        self.security_group = self._create_security_group()
        security_groups = [{'name': self.security_group['name']}]
        self.md = {'meta1': 'data1', 'meta2': 'data2', 'metaN': 'dataN'}
        self.instance = self.create_server(
            image_id=self.image_ref,
            flavor=self.flavor_ref,
            key_name=keypair['name'],
            security_groups=security_groups,
            config_drive=CONF.compute_feature_enabled.config_drive,
            metadata=self.md,
            wait_until='ACTIVE')
        self.verify_ssh(keypair)
        self.verify_metadata()
        self.servers_client.delete_server(self.instance['id'])
