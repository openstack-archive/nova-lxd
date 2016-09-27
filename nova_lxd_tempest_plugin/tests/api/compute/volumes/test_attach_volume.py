# Copyright 2012 OpenStack Foundation
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

from pylxd import client

from tempest.api.compute import base
from tempest.common.utils import data_utils
from tempest.common import waiters
from tempest import config
from tempest import test

CONF = config.CONF


class LXDVolumeTests(base.BaseV2ComputeAdminTest):
    disk_config = 'AUTO'

    def __init__(self, *args, **kwargs):
        super(LXDVolumeTests, self).__init__(*args, **kwargs)
        self.attachment = None
        self.client = client.Client()

    @classmethod
    def setup_credentials(cls):
        cls.prepare_instance_network()
        super(LXDVolumeTests, cls).setup_credentials()

    @classmethod
    def setup_clients(cls):
        super(LXDVolumeTests, cls).setup_clients()
        cls.client = cls.os_adm.servers_client
        cls.flavors_client = cls.os_adm.flavors_client

    @classmethod
    def resource_setup(cls):
        cls.set_validation_resources()
        super(LXDVolumeTests, cls).resource_setup()
        cls.meta = {'hello': 'world'}
        cls.accessIPv4 = '1.1.1.1'
        cls.accessIPv6 = '0000:0000:0000:0000:0000:babe:220.12.22.2'
        cls.name = data_utils.rand_name(cls.__name__ + '-server')
        cls.password = data_utils.rand_password()
        disk_config = cls.disk_config
        cls.server_initial = cls.create_test_server(
            validatable=True,
            wait_until='ACTIVE',
            name=cls.name,
            metadata=cls.meta,
            accessIPv4=cls.accessIPv4,
            accessIPv6=cls.accessIPv6,
            disk_config=disk_config,
            adminPass=cls.password)
        cls.server = (
            cls.client.show_server(cls.server_initial['id'])['server'])
        cls.device = CONF.compute.volume_device_name

    def _detach(self, server_id, volume_id):
        if self.attachment:
            self.servers_client.detach_volume(server_id, volume_id)
            waiters.wait_for_volume_status(self.volumes_client,
                                           volume_id, 'available')

    def _create_and_attach_volume(self, server):
        # Create a volume and wait for it to become ready
        vol_name = data_utils.rand_name(self.__class__.__name__ + '-volume')
        volume = self.volumes_client.create_volume(
            size=CONF.volume.volume_size, display_name=vol_name)['volume']
        self.addCleanup(self.delete_volume, volume['id'])
        waiters.wait_for_volume_status(self.volumes_client,
                                       volume['id'], 'available')

        # Attach the volume to the server
        self.attachment = self.servers_client.attach_volume(
            server['id'],
            volumeId=volume['id'],
            device='/dev/%s' % self.device)['volumeAttachment']
        waiters.wait_for_volume_status(self.volumes_client,
                                       volume['id'], 'in-use')

        self.addCleanup(self._detach, server['id'], volume['id'])
        return volume

    def test_create_server_and_attach_volume(self):
        # Verify that LXD profile has the correct configuration
        # for volumes
        volume = self._create_and_attach_volume(self.server)

        profile = self.client.profiles.get(
            self.server['OS-EXT-SRV-ATTR:instance_name'])

        self.assertIn(volume['id'], [device for device in profile.devices])
        self.assertEqual(
            '/dev/%s' % self.device, profile.devices[volume['id']]['path'])
