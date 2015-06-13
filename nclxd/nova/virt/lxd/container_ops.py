import sys

from oslo_config import cfg
from oslo_log import log as logging

from pylxd import api

from nova.i18n import _, _LE, _LI
from nova import exception
from nova import utils
from nova.virt import driver

CONF = cfg.CONF
LOG = logging.getLogger(__name__)

class LXDOperations(object):

    def __init__(self, virtapi):
        self.virtapi = virtapi
        self.lxd = api.API()

    def container_init_host(self, hostname):
        """ Make sure that the LXD daemon is starting
        before trying to run a container
        """
        LOG.debug('Running container init_host.')
        try:
            self.lxd.host_ping()
        except Exception as ex:
            msg = _('Unable to connect to LXD host')
            raise exception.NovaException(msg)

    def container_list(self):
        """Return the names of all the instances known to the
        LXD daemon.
        """
        LOG.debug('Running continer_list')
        try:
            return self.lxd.container_list()
        except Exception as ex:
            msg = _('Unable to list containers.')
            raise exception.NovaException(msg)
