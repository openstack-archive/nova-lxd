import sys

from oslo_config import cfg
from oslo_log import log as logging


from nova.i18n import _, _LE, _LI
from nova import exception
from nova import utils
from nova.virt import driver

CONF = cfg.CONF
LOG = logging.getLogger(__name__)