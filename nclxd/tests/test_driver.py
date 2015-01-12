import nova.tests.unit.virt import test_virt_drivers

class LXDDriverTestCase(test_virt_drivers._VirtDriverTestCase,
                        test.TestCase):
    def setUp(self):
        super(LXDDriverTestCase, self).setUp()

