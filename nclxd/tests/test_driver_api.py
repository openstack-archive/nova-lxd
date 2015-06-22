

import contextlib
import platform

import mock

from oslo_config import cfg

from nova import context
from nova import test
from nova.virt import fake
from nova.tests.unit import fake_network
from nova.tests.unit import fake_instance
from nclxd.nova.virt.lxd import driver
from nova import exception
from nova import utils

from nclxd.nova.virt.lxd import container_ops

CONF = cfg.CONF

class LXDTestDriver(test.NoDBTestCase):
    def setUp(self):
        super(LXDTestDriver, self).setUp()
        self.connection = driver.LXDDriver(fake.FakeVirtAPI())

    def test_capabilities(self):
        self.assertFalse(self.connection.capabilities['has_imagecache'])
        self.assertFalse(self.connection.capabilities['supports_recreate'])
        self.assertFalse(self.connection.capabilities[
                        'supports_migrate_to_same_host'])
