from nova import exception
from shade import exc

from testing import FunctionalTestCase

class LXDTestServerActions(FunctionalTestCase):
    def test_create_test_server(self):
        image = self.cloud.get_image('lxd')
        server =  self.cloud.create_server(
            'my-server', image=image.id, flavor=self.flavor.id,
            wait=True)
        self.wait_for_instance_status(server.id, 'ACTIVE')
        instance = self.nova.servers.get(server.id)
        self.assertEqual('ACTIVE', instance.status)
        self.cloud.delete_server(server.id, wait=True)

    def test_create_and_delete_server(self):
        image = self.cloud.get_image('lxd')
        server =  self.cloud.create_server(
            'my-server', image=image.id, flavor=self.flavor.id,
            wait=True)
        self.wait_for_instance_status(server.id, 'ACTIVE')
        instance = self.nova.servers.get(server.id)
        self.assertEqual('ACTIVE', instance.status)
        self.cloud.delete_server(server.id, wait=True)

    def test_create_server_invalid_iso_image(self):
        image = self.create_image('lxd-iso', disk_format='iso')
        self.assertRaises(
            exc.OpenStackCloudException,
            self.cloud.create_server,
            'my-server', image=image.id, flavor=self.flavor.id,
            wait=True)

    def test_create_server_invalid_qcow2_image(self):
        image = self.create_image('lxd-qcow2', disk_format='qcow2')
        self.assertRaises(
            exc.OpenStackCloudException,
            self.cloud.create_server, 'my-server', image=image.id,
            flavor=self.flavor.id, wait=True)

    def test_suspend_and_resume_server(self):
        image = self.cloud.get_image('lxd')
        server = self.cloud.create_server(
            'my-server', image=image.id, flavor=self.flavor.id,
            wait=True)
        self.wait_for_instance_status(server.id, 'ACTIVE')
        self.nova.servers.suspend(server.id)
        self.wait_for_instance_status(server.id, 'SUSPENDED')
        self.assertEqual('SUSPENDED', self.nova.servers.get(server.id).status)
        self.nova.servers.resume(server.id)
        self.wait_for_instance_status(server.id, 'ACTIVE')
        self.assertEqual('ACTIVE', self.nova.servers.get(server.id).status)
        self.cloud.delete_server(server.id, wait=True)

    def test_pause_and_unpause_server(self):
        image = self.cloud.get_image('lxd')
        server = self.cloud.create_server(
            'my-server', image=image.id, flavor=self.flavor.id,
            wait=True)
        self.wait_for_instance_status(server.id, 'ACTIVE')
        self.nova.servers.pause(server.id)
        self.wait_for_instance_status(server.id, 'PAUSED')
        self.assertEqual('PAUSED', self.nova.servers.get(server.id).status)
        self.nova.servers.unpause(server.id)
        self.wait_for_instance_status(server.id, 'ACTIVE')
        self.assertEqual('ACTIVE', self.nova.servers.get(server.id).status)
        self.cloud.delete_server(server.id, wait=True)
