import os

from oslo.config import cfg
from oslo_log import log as logging

from nova.i18n import _, _LW, _LE, _LI
from nova import utils
from nova import exception

from . import constants

CONF = cfg.CONF
LOG = logging.getLogger(__name__)


class ContainerConfig(object):
    def __init__(self, client):
        self.client = client
        self.config = {}
        self.resources = {}
        self.devices = {}

    def create_container_config(self, instance, network_info):
        self.config = { 'name': instance.uuid,
                       'architecture':  'x86_64',
                       'ephemeral': True,
                       'hostname': instance.uuid,
                       'profiles': [],
        }
        self.config['source'] = {'type': 'image',
                            'alias': instance.image_ref}

        self.config['devices'] = { 'eth0':
                                    self._get_container_devices(network_info)}

        self.config['config'] = {'raw.lxc': 'lxc.console.logfile = %s'
                                            % self._get_console_path(instance),
                                 'limits.memory': '%s' % self._get_memory_mb(instance),
                                 'limits.cpus': '%s' % self._get_vcpus(instance)
                                 }

        LOG.debug(_('Creating container configuration'))
        self._container_init(instance)

    def _container_init(self, instance):
        try:
            (status, resp) = self.client.container_init(self.config)
            if resp.get('status') != 'OK':
                raise exception.NovaException
        except Exception as e:
            LOG.debug(_('Failed to init container: %s') % resp.get('metadata'))
            msg = _('Cannot init container: {0}')
            raise exception.NovaException(msg.format(e),
                                          instance_id=instance.name)


    def _get_container_devices(self, network_info):
        for vif in network_info:
            vif_id = vif['id'][:11]
            vif_type = vif['type']
            bridge = vif['network']['bridge']
            mac = vif['address']

        if vif_type == 'ovs':
            bridge = 'qbr%s' % vif_id

        return {
            'type': 'nic',
            'parent': bridge,
            'hwaddr': mac,
        }

    def _get_memory_mb(self, instance):
        if instance.flavor is not None:
            try:
                memory_mb = '%sM' % int(instance.flavor.memory_mb)
            except ValueError:
                raise Exception('Failed to determine memory for container.')
        return memory_mb

    def _get_vcpus(self, instance):
        if instance.flavor is not None:
            try:
                vcpus = instance.flavor.vcpus
            except ValueError:
                raise Exception('Failed to determine vcpus for container.')
        return vcpus

    def _get_console_path(self, instance):
        return os.path.join(CONF.lxd.lxd_root_dir, instance.uuid, 'console.log')