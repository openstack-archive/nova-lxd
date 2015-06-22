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

class LXDTestContainerOps(test.NoDBTestCase):
    def setUp(self):
        super(LXDTestContainerOps, self).setUp()