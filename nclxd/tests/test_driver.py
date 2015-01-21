import fixtures

from oslo.config import cfg
import mock

from nova import test
from nova.tests.unit import utils
from nova.tests.unit.image import fake as fake_image
import nclxd.nova.virt.lxd

from nclxd.nova.virt.lxd import driver
from nclxd.nova.virt.lxd import container

CONF = cfg.CONF
CONF.import_opt('image_cache_subdirectory_name', 'nova.virt.imagecache')

class LXDTestDriver(test.TestCase):
    def setUp(self):
        super(LXDTestDriver, self).setUp()

        self.ctxt = utils.get_test_admin_context()
        fake_image.stub_out_image_service(self.stubs)
        self.driver = driver.LXDDriver(None, None)
