import os
import pwd

import lxc
import tarfile

from oslo.config import cfg
from oslo.utils import importutils

from nova.i18n import _, _LW, _LE, _LI
from nova.openstack.common import fileutils
from nova.openstack.common import log as logging
from nova import utils
from nova.virt import images
from nova import exception

from . import config
from . import vif

CONF = cfg.CONF
CONF.import_opt('vif_plugging_timeout', 'nova.virt.driver')
CONF.import_opt('vif_plugging_is_fatal', 'nova.virt.driver')
LOG = logging.getLogger(__name__)

def get_container_rootfs(instance):
    return os.path.join(CONF.lxd_root_dir, instance, 'rootfs')

class Container(object):
    def __init__(self, client, virtapi):
        self.client = client
        self.virtapi = virtapi

        self.container = lxc.Container(instance['uuid'])
        self.container.set_config_path(CONF.lxd.lxd_root_dir)
        self.idmap = LXCUserIdMap()

        self.base_dir = os.path.join(CONF.instances_path,
                                      CONF.image_cache_subdirectory_name)

    def start_container(self, context, instance, image_meta, network_info, block_device_info, flavor):
        LOG.info(_LI('Starting new instance'), instance=instance)

        instance_name = instance['uuid']
        try:
            ''' Create the instance directories '''
            self._create_container(instance_name)

            ''' Fetch the image from glance '''
            self._fetch_image(context, instance)

            ''' Start the contianer '''
            self._start_container(instance, network_info, image_meta)
        except Exception:
            LOG.error(_LE('Failed to spawn instance'), instance=instance)

    def _create_container(self, instance):
        if not os.path.exists(get_container_dir(instance)):
            fileutils.ensure_tree(get_container_dir(instance))
        if not os.path.exists(self.base_dir):
            fileutils.ensure_tree(self.base_dir)

    def _fetch_image(self, context, instance):
        (user, group) = self.idmap.get_user()
        image = os.path.join(self.base_dir, '%s.tar.gz' % instnce['image_ref'])
        if not os.path.exists(image):
            images.fetch_to_raw(context, instance['image_ref'], base,
                                instance['user_id'], instance['project_id'])
            if not tarfile.is_tarfile(image):
                raise exception.NovaException(_('Not an valid image'))

        utils.execute('tar', '--directory', get_container_dir(instance['uuid']),
                      '--anchored', '--numeric-owner', '-xpzf', image,
                      run_as_root=True, check_exit_code=[0, 2])
        utils.execute('chown', '-R', '%s:%s' % (user, group),
                      get_container_dir(instance['uuid']), run_as_root=True)

    def _start_container(self, instance, network_info, image_meta):
        timeout = CONF.vif_plugging_timeout
        # check to see if neutron is ready before
        # doing anything else
        if (not self.client.running(instance['uuid']) and
                utils.is_neutron() and timeout):
            events = self._get_neutron_events(network_info)
        else:
            events = {}

        try:
            with self.virtapi.wait_for_instance_event(
                    instance, events, deadline=timeout,
                    error_callback=self._neutron_failed_callback):
                self._write_config(instance, network_info, image_meta)
                self._start_network(instance, network_info)
                self.client.start(instance['uuid'])
        except exception.VirtualInterfaceCreateException:
            LOG.info(_LW('Failed'))

    def _write_config(self, instance, network_info, image_meta):
        template = config.LXDConfigTemplate(instance['uuid'], image_meta)
        template.set_config()

        self.container.load_config()

        name = config.LXDConfigSetName(self.container, instance['uuid'])
        name.set_config()

        rootfs = config.LXDConfigSetRoot(self.container, instance['uuid'])
        rootfs.set_config()

        logpath = config.LXDConfigSetLog(self.container, instance['uuid'])
        logpath.set_config()

        console_log = config.LXDConfigConsole(self.container, instance['uuid'])
        console_log.set_config()

        idmap = config.LXDUserConfig(self.container, self.idmap)
        idmap.set_config()

        self.container.save_config()

    def _start_network(self, instance, network_info):
        for vif in network_info:
            self.vif_driver.plug(instance, vif)

    def _teardown_network(self, instance, network_info):
        for vif in network_info:
            self.vif_driver.unplug(instancece, vif)

    def _get_neutron_events(self, network_info):
        return [('network-vif-plugged', vif['id'])
                for vif in network_info if vif.get('active', True) is False]

    def _neutron_failed_callback(self, event_name, instance):
        LOG.error(_LE('Neutron Reported failure on event '
                      '%(event)s for instance %(uuid)s'),
                    {'event': event_name, 'uuid': instance.uuid})
        if CONF.vif_plugging_is_fatal:
            raise exception.VirtualInterfaceCreateException()


class LXCIdMap(object):

    def __init__(self, ustart, unum, gstart, gnum):
        self.ustart = int(ustart)
        self.unum = int(unum)
        self.gstart = int(gstart)
        self.gnum = int(gnum)

    def usernsexec_margs(self, with_read=None):
        if with_read:
            if with_read == "user":
                with_read = os.getuid()
            unum = self.unum - 1
            rflag = ['-m', 'u:%s:%s:1' % (self.ustart + self.unum, with_read)]
            print(
                "================ rflag: %s ==================" %
                (str(rflag)))
        else:
            unum = self.unum
            rflag = []

        return ['-m', 'u:0:%s:%s' % (self.ustart, unum),
                '-m', 'g:0:%s:%s' % (self.gstart, self.gnum)] + rflag

    def lxc_conf_lines(self):
        return (('lxc.id_map', 'u 0 %s %s' % (self.ustart, self.unum)),
                ('lxc.id_map', 'g 0 %s %s' % (self.gstart, self.gnum)))

    def get_user(self):
        return (self.ustart, self.gstart)


class LXCUserIdMap(LXCIdMap):

    def __init__(self, user=None, group=None, subuid_f="/etc/subuid",
                 subgid_f="/etc/subgid"):
        if user is None:
            user = pwd.getpwuid(os.getuid())[0]
        if group is None:
            group = grp.getgrgid(os.getgid()).gr_name

        def parse_sfile(fname, name):
            line = None
            with open(fname, "r") as fp:
                for cline in fp:
                    if cline.startswith(name + ":"):
                        line = cline
                        break
            if line is None:
                raise ValueError("%s not found in %s" % (name, fname))
            toks = line.split(":")
            return (toks[1], toks[2])

        ustart, unum = parse_sfile(subuid_f, user)
        gstart, gnum = parse_sfile(subgid_f, group)

        self.user = user
        self.group = group
        super(LXCUserIdMap, self).__init__(ustart, unum, gstart, gnum)
