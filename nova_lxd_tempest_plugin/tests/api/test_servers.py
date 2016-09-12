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

import os

from pylxd import client

from tempest.api.compute import base
from tempest.common.utils import data_utils
from tempest.common.utils.linux import remote_client
from tempest import config

CONF = config.CONF


class LXDServersWithSpecificFlavorTestJSON(base.BaseV2ComputeAdminTest):
    disk_config = 'AUTO'

    @classmethod
    def setup_credentials(cls):
        cls.prepare_instance_network()
        super(LXDServersWithSpecificFlavorTestJSON, cls).setup_credentials()

    @classmethod
    def setup_clients(cls):
        super(LXDServersWithSpecificFlavorTestJSON, cls).setup_clients()
        cls.flavor_client = cls.os_adm.flavors_client
        cls.client = cls.os_adm.servers_client

    @classmethod
    def resource_setup(cls):
        cls.set_validation_resources()

        super(LXDServersWithSpecificFlavorTestJSON, cls).resource_setup()

    def test_verify_created_server_ephemeral_disk(self):
        # Verify that the ephemeral disk is created when creating server
        flavor_base = self.flavors_client.show_flavor(
            self.flavor_ref)['flavor']

        def create_flavor_with_extra_specs():
            flavor_with_eph_disk_name = data_utils.rand_name('eph_flavor')
            flavor_with_eph_disk_id = data_utils.rand_int_id(start=1000)

            ram = flavor_base['ram']
            vcpus = flavor_base['vcpus']
            disk = flavor_base['disk']

            # Create a flavor with extra specs
            flavor = (self.flavor_client.
                      create_flavor(name=flavor_with_eph_disk_name,
                                    ram=ram, vcpus=vcpus, disk=disk,
                                    id=flavor_with_eph_disk_id,
                                    ephemeral=1))['flavor']
            self.addCleanup(flavor_clean_up, flavor['id'])

            return flavor['id']

        def create_flavor_without_extra_specs():
            flavor_no_eph_disk_name = data_utils.rand_name('no_eph_flavor')
            flavor_no_eph_disk_id = data_utils.rand_int_id(start=1000)

            ram = flavor_base['ram']
            vcpus = flavor_base['vcpus']
            disk = flavor_base['disk']

            # Create a flavor without extra specs
            flavor = (self.flavor_client.
                      create_flavor(name=flavor_no_eph_disk_name,
                                    ram=ram, vcpus=vcpus, disk=disk,
                                    id=flavor_no_eph_disk_id))['flavor']
            self.addCleanup(flavor_clean_up, flavor['id'])

            return flavor['id']

        def flavor_clean_up(flavor_id):
            self.flavor_client.delete_flavor(flavor_id)
            self.flavor_client.wait_for_resource_deletion(flavor_id)

        flavor_with_eph_disk_id = create_flavor_with_extra_specs()

        admin_pass = self.image_ssh_password

        server_with_eph_disk = self.create_test_server(
            validatable=True,
            wait_until='ACTIVE',
            adminPass=admin_pass,
            flavor=flavor_with_eph_disk_id)

        server_with_eph_disk = self.client.show_server(
            server_with_eph_disk['id'])['server']

        linux_client = remote_client.RemoteClient(
            self.get_server_ip(server_with_eph_disk),
            self.ssh_user,
            admin_pass,
            self.validation_resources['keypair']['private_key'],
            server=server_with_eph_disk,
            servers_client=self.client)
        cmd = 'sudo touch /mnt/tempest.txt'
        linux_client.exec_command(cmd)

        lxd = client.Client()
        profile = lxd.profiles.get(server_with_eph_disk[
            'OS-EXT-SRV-ATTR:instance_name'])
        tempfile = '%s/tempest.txt' % profile.devices['ephemeral0']['source']
        self.assertTrue(os.path.exists(tempfile))
