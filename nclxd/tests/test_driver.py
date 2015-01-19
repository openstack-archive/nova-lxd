from mox3 import mox
from oslo.utils import units

from nova import db
from nova.compute import flavors
from nova.compute import power_state
from nova import context
from nova import test
from nova.tests.unit import utils

from nclxd.nova.virt.lxd import driver as connection
from nclxd.nova.virt.lxd import client

class TestLXDDriver(test.NoDBTestCase):
    def setUp(self):
        super(TestLXDDriver, self).setUp()

        self.context = context.RequestContext('fake_user', 'fake_project')

    def test_get_container_state(self):
        instance = utils.get_test_instance()
        state = self.connection.get_info(instance)
        self.assertEqual(state['state'], power_state.RUNNING)