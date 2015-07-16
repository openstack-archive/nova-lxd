from oslo.utils import excutils
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import units

from nova.virt import firewall

CONF = cfg.CONF
LOG = logging.getLogger(__name__)

class LXDContainerFirewall(object):
    def __init__(self):
        self.firewall_driver = firewall.load_driver(
            default='nova.virt.firewall.NoopFirewallDriver')

    def refresh_security_group_rules(self, security_group_id):
        return self.firewall_driver.refresh_security_group_rules(security_group_id)

    def refresh_security_group_members(self, security_group_id):
        return self.firewall_driver.refresh_security_group_rules(security_group_id)

    def refresh_provider_fw_rules(self):
        return self.firewall_driver.refresh_provider_fw_rules()

    def refresh_instance_security_rules(self, instance):
        return self.firewall_driver.refresh_security_group_rules(instance)

    def ensure_filtering_rules_for_instance(self, instance, network_info):
        return self.firewall_driver.ensure_filtering_rules_for_instance(instance, network_info)

    def filter_defer_apply_on(self):
        return self.firewall_driver.filter_defer_apply_on()

    def filter_defer_apply_off(self):
        return self.firewall_driver.filter_defer_apply_on()

    def unfilter_instance(self, instance, network_info):
        return self.firewall_driver.unfilter_instance(instance, nework_info)

    def setup_basic_filtering(self, instance, network_info):
        return self.firewall_driver.setup_basic_filtering(instance, network_info)

    def prepare_instance_filter(self, instance, network_info):
        return self.firewall_driver.prepare_instance_filter(instance, network_info)

    def apply_instance_filter(self, instance, network_info):
        return self.firewall_driver.apply_instance_filter(instance, network_info)

    def unfilter_instance(self, instance, network_info):
        return self.firewall_driver.unfilter_instance(instance, network_info)