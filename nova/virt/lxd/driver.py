# Copyright 2015 Canonical Ltd
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

from __future__ import absolute_import

import io
import json
import os
import platform
import pwd
import shutil
import socket
import tarfile
import tempfile

import eventlet
import nova.conf
import nova.context
from nova import exception
from nova import i18n
from nova import image
from nova import network
from nova.network import model as network_model
from nova import objects
from nova.virt import driver
from os_brick.initiator import connector
from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import fileutils
import pylxd
from pylxd import exceptions as lxd_exceptions

from nova.virt.lxd import vif as lxd_vif
from nova.virt.lxd import common
from nova.virt.lxd import flavor
from nova.virt.lxd import storage

from nova.api.metadata import base as instance_metadata
from nova.objects import fields as obj_fields
from nova.objects import migrate_data
from nova.virt import configdrive
from nova.compute import power_state
from nova.compute import vm_states
from nova.virt import hardware
from oslo_utils import units
from oslo_serialization import jsonutils
from nova import utils
import psutil
from oslo_concurrency import lockutils
from nova.compute import task_states
from oslo_utils import excutils
from nova.virt import firewall

_ = i18n._
_LW = i18n._LW
_LE = i18n._LE

lxd_opts = [
    cfg.StrOpt('root_dir',
               default='/var/lib/lxd/',
               help='Default LXD directory'),
    cfg.IntOpt('timeout',
               default=-1,
               help='Default LXD timeout'),
    cfg.BoolOpt('allow_live_migration',
                default=False,
                help='Determine wheter to allow live migration'),
]

CONF = cfg.CONF
CONF.register_opts(lxd_opts, 'lxd')
LOG = logging.getLogger(__name__)
IMAGE_API = image.API()

MAX_CONSOLE_BYTES = 100 * units.Ki
NOVA_CONF = nova.conf.CONF

ACCEPTABLE_IMAGE_FORMATS = {'raw', 'root-tar', 'squashfs'}
BASE_DIR = os.path.join(
    CONF.instances_path, CONF.image_cache_subdirectory_name)


def _neutron_failed_callback(event_name, instance):
    LOG.error(_LE('Neutron Reported failure on event '
                  '%(event)s for instance %(uuid)s'),
              {'event': event_name, 'uuid': instance.name},
              instance=instance)
    if CONF.vif_plugging_is_fatal:
        raise exception.VirtualInterfaceCreateException()


def _get_cpu_info():
    """Get cpu information.

    This method executes lscpu and then parses the output,
    returning a dictionary of information.
    """
    cpuinfo = {}
    out, err = utils.execute('lscpu')
    if err:
        msg = _('Unable to parse lscpu output.')
        raise exception.NovaException(msg)

    cpu = [line.strip('\n') for line in out.splitlines()]
    for line in cpu:
        if line.strip():
            name, value = line.split(':', 1)
            name = name.strip().lower()
            cpuinfo[name] = value.strip()

    f = open('/proc/cpuinfo', 'r')
    features = [line.strip('\n') for line in f.readlines()]
    for line in features:
        if line.strip():
            if line.startswith('flags'):
                name, value = line.split(':', 1)
                name = name.strip().lower()
                cpuinfo[name] = value.strip()

    return cpuinfo


def _get_ram_usage():
    """Get memory info."""
    with open('/proc/meminfo') as fp:
        m = fp.read().split()
        idx1 = m.index('MemTotal:')
        idx2 = m.index('MemFree:')
        idx3 = m.index('Buffers:')
        idx4 = m.index('Cached:')

        total = int(m[idx1 + 1])
        avail = int(m[idx2 + 1]) + int(m[idx3 + 1]) + int(m[idx4 + 1])

    return {
        'total': total * 1024,
        'used': (total - avail) * 1024
    }


def _get_fs_info(path):
    """Get free/used/total disk space."""
    hddinfo = os.statvfs(path)
    total = hddinfo.f_blocks * hddinfo.f_bsize
    available = hddinfo.f_bavail * hddinfo.f_bsize
    used = total - available
    return {'total': total,
            'available': available,
            'used': used}


def _get_power_state(lxd_state):
    """Take a lxd state code and translate it to nova power state."""
    state_map = [
        (power_state.RUNNING, {100, 101, 103, 200}),
        (power_state.SHUTDOWN, {102, 104, 107}),
        (power_state.NOSTATE, {105, 106, 401}),
        (power_state.CRASHED, {108, 400}),
        (power_state.SUSPENDED, {109, 110, 111}),
    ]
    for nova_state, lxd_states in state_map:
        if lxd_state in lxd_states:
            return nova_state
    raise ValueError('Unknown LXD power state: {}'.format(lxd_state))


def _sync_glance_image_to_lxd(client, context, image_ref):
    """Sync an image from glance to LXD image store.

    The image from glance can't go directly into the LXD image store,
    as LXD needs some extra metadata connected to it.

    The image is stored in the LXD image store with an alias to
    the image_ref. This way, it will only copy over once.
    """
    lock_path = os.path.join(CONF.instances_path, 'locks')
    with lockutils.lock(
            lock_path, external=True,
            lock_file_prefix='lxd-image-{}'.format(image_ref)):

        try:
            image_file = tempfile.mkstemp()[1]
            manifest_file = tempfile.mkstemp()[1]

            image = IMAGE_API.get(context, image_ref)
            if image.get('disk_format') not in ACCEPTABLE_IMAGE_FORMATS:
                raise exception.ImageUnacceptable(
                    image_id=image_ref, reason=_('Bad image format'))
            IMAGE_API.download(context, image_ref, dest_path=image_file)

            metadata = {
                'architecture': image.get(
                    'hw_architecture', obj_fields.Architecture.from_host()),
                'creation_date': int(os.stat(image_file).st_ctime)}
            metadata_yaml = json.dumps(
                metadata, sort_keys=True, indent=4,
                separators=(',', ': '),
                ensure_ascii=False).encode('utf-8') + b"\n"

            tarball = tarfile.open(manifest_file, "w:gz")
            tarinfo = tarfile.TarInfo(name='metadata.yaml')
            tarinfo.size = len(metadata_yaml)
            tarball.addfile(tarinfo, io.BytesIO(metadata_yaml))
            tarball.close()

            with open(manifest_file, 'rb') as manifest:
                with open(image_file, 'rb') as image:
                    image = client.images.create(
                        image.read(), metadata=manifest.read(),
                        wait=True)
            image.add_alias(image_ref, '')

        finally:
            os.unlink(image_file)
            os.unlink(manifest_file)


class LXDLiveMigrateData(migrate_data.LiveMigrateData):
    """LiveMigrateData for LXD."""

    VERSION = '1.0'
    fields = {}


class LXDDriver(driver.ComputeDriver):
    """A LXD driver for nova.

    LXD is a system container hypervisor. LXDDriver provides LXD
    functionality to nova. For more information about LXD, see
    http://www.ubuntu.com/cloud/lxd
    """

    capabilities = {
        "has_imagecache": False,
        "supports_recreate": False,
        "supports_migrate_to_same_host": False,
        "supports_attach_interface": True
    }

    def __init__(self, virtapi):
        super(LXDDriver, self).__init__(virtapi)

        self.client = None  # Initialized by init_host
        self.host = NOVA_CONF.host
        self.network_api = network.API()
        self.vif_driver = lxd_vif.LXDGenericVifDriver()
        self.firewall_driver = firewall.load_driver(
            default='nova.virt.firewall.NoopFirewallDriver')

        self.storage_driver = connector.InitiatorConnector.factory(
            'ISCSI', utils.get_root_helper(),
            use_multipath=CONF.libvirt.volume_use_multipath,
            device_scan_attempts=CONF.libvirt.num_iscsi_scan_tries,
            transport='default')

    def init_host(self, host):
        """Initialize the driver on the host.

        The pylxd Client is initialized. This initialization may raise
        an exception if the LXD instance cannot be found.

        The `host` argument is ignored here, as the LXD instance is
        assumed to be on the same system as the compute worker
        running this code. This is by (current) design.

        See `nova.virt.driver.ComputeDriver.init_host` for more
        information.
        """
        try:
            self.client = pylxd.Client()
        except lxd_exceptions.ClientConnectionFailed as e:
            msg = _('Unable to connect to LXD daemon: %s') % e
            raise exception.HostNotFound(msg)
        self._after_reboot()

    def cleanup_host(self, host):
        """Clean up the host.

        `nova.virt.ComputeDriver` defines this method. It is overridden
        here to be explicit that there is nothing to be done, as
        `init_host` does not create any resources that would need to be
        cleaned up.

        See `nova.virt.driver.ComputeDriver.cleanup_host` for more
        information.
        """

    def get_info(self, instance):
        """Return an InstanceInfo object for the instance."""
        container = self.client.containers.get(instance.name)

        state = container.state()
        mem_kb = state.memory['usage'] >> 10
        max_mem_kb = state.memory['usage_peak'] >> 10
        return hardware.InstanceInfo(
            state=_get_power_state(state.status_code),
            max_mem_kb=max_mem_kb,
            mem_kb=mem_kb,
            num_cpu=instance.flavor.vcpus,
            cpu_time_ns=0)

    def list_instances(self):
        """Return a list of all instance names."""
        return [c.name for c in self.client.containers.all()]

    def spawn(self, context, instance, image_meta, injected_files,
              admin_password, network_info=None, block_device_info=None):
        """Create a new lxd container as a nova instance.

        Creating a new container requires a number of steps. First, the
        image is fetched from glance, if needed. Next, the network is
        connected. A profile is created in LXD, and then the container
        is created and started.

        See `nova.virt.driver.ComputeDriver.spawn` for more
        information.
        """
        try:
            self.client.containers.get(instance.name)
            raise exception.InstanceExists(name=instance.name)
        except lxd_exceptions.LXDAPIException as e:
            if e.response.status_code != 404:
                raise  # Re-raise the exception if it wasn't NotFound

        instance_dir = common.InstanceAttributes(instance).instance_dir
        if not os.path.exists(instance_dir):
            fileutils.ensure_tree(instance_dir)

        # Check to see if LXD already has a copy of the image. If not,
        # fetch it.
        try:
            self.client.images.get_by_alias(instance.image_ref)
        except lxd_exceptions.LXDAPIException as e:
            if e.response.status_code != 404:
                raise
            _sync_glance_image_to_lxd(
                self.client, context, instance.image_ref)

        # Plug in the network
        if network_info:
            timeout = CONF.vif_plugging_timeout
            if (utils.is_neutron() and timeout):
                events = [('network-vif-plugged', vif['id'])
                          for vif in network_info if not vif.get(
                    'active', True)]
            else:
                events = []

            try:
                with self.virtapi.wait_for_instance_event(
                        instance, events, deadline=timeout,
                        error_callback=_neutron_failed_callback):
                    self.plug_vifs(instance, network_info)
            except eventlet.timeout.Timeout:
                LOG.warn(_LW('Timeout waiting for vif plugging callback for '
                             'instance %(uuid)s'), {'uuid': instance['name']})
                if CONF.vif_plugging_is_fatal:
                    self.destroy(
                        context, instance, network_info, block_device_info)
                    raise exception.InstanceDeployFailure(
                        'Timeout waiting for vif plugging',
                        instance_id=instance['name'])

        # Create the profile
        try:
            profile = flavor.to_profile(
                self.client, instance, network_info, block_device_info)
        except lxd_exceptions.LXDAPIException as e:
            with excutils.save_and_reraise_exception():
                self.cleanup(
                    context, instance, network_info, block_device_info)

        # Create the container
        container_config = {
            'name': instance.name,
            'profiles': [profile.name],
            'source': {
                'type': 'image',
                'alias': instance.image_ref,
            },
        }
        try:
            container = self.client.containers.create(
                container_config, wait=True)
        except lxd_exceptions.LXDAPIException as e:
            with excutils.save_and_reraise_exception():
                self.cleanup(
                    context, instance, network_info, block_device_info)

        lxd_config = self.client.host_info
        storage.attach_ephemeral(
            self.client, block_device_info, lxd_config, instance)
        if configdrive.required_by(instance):
            configdrive_path = self._add_configdrive(
                context, instance,
                injected_files, admin_password,
                network_info)

            profile = self.client.profiles.get(instance.name)
            config_drive = {
                'configdrive': {
                    'path': '/var/lib/cloud/data',
                    'source': configdrive_path,
                    'type': 'disk',
                }
            }
            profile.devices.update(config_drive)
            profile.save()

        try:
            self.firewall_driver.setup_basic_filtering(
                instance, network_info)
            self.firewall_driver.instance_filter(
                instance, network_info)

            container.start(wait=True)

            self.firewall_driver.apply_instance_filter(
                instance, network_info)
        except lxd_exceptions.LXDAPIException as e:
            with excutils.save_and_reraise_exception():
                self.cleanup(
                    context, instance, network_info, block_device_info)

    def destroy(self, context, instance, network_info, block_device_info=None,
                destroy_disks=True, migrate_data=None):
        """Destroy a running instance.

        Since the profile and the instance are created on `spawn`, it is
        safe to delete them together.

        See `nova.virt.driver.ComputeDriver.destroy` for more
        information.
        """
        try:
            container = self.client.containers.get(instance.name)
            if container.status != 'Stopped':
                container.stop(wait=True)
            container.delete(wait=True)
        except lxd_exceptions.LXDAPIException as e:
            if e.response.status_code == 404:
                LOG.warning(_LW('Failed to delete instance. '
                                'Container does not exist for %(instance)s.'),
                            {'instance': instance.name})
            else:
                raise
        finally:
            self.cleanup(
                context, instance, network_info, block_device_info)

    def cleanup(self, context, instance, network_info, block_device_info=None,
                destroy_disks=True, migrate_data=None, destroy_vifs=True):
        """Clean up the filesystem around the container.

        See `nova.virt.driver.ComputeDriver.cleanup` for more
        information.
        """
        if destroy_vifs:
            self.unplug_vifs(instance, network_info)
            self.firewall_driver.unfilter_instance(instance, network_info)

        lxd_config = self.client.host_info
        storage.detach_ephemeral(block_device_info, lxd_config, instance)

        name = pwd.getpwuid(os.getuid()).pw_name

        container_dir = common.InstanceAttributes(instance).instance_dir
        if os.path.exists(container_dir):
            utils.execute(
                'chown', '-R', '{}:{}'.format(name, name),
                container_dir, run_as_root=True)
            shutil.rmtree(container_dir)

        try:
            self.client.profiles.get(instance.name).delete()
        except lxd_exceptions.LXDAPIException as e:
            if e.response.status_code == 404:
                LOG.warning(_LW('Failed to delete instance. '
                                'Profile does not exist for %(instance)s.'),
                            {'instance': instance.name})
            else:
                raise

    def reboot(self, context, instance, network_info, reboot_type,
               block_device_info=None, bad_volumes_callback=None):
        """Reboot the container.

        Nova *should* not execute this on a stopped container, but
        the documentation specifically says that if it is called, the
        container should always return to a 'Running' state.

        See `nova.virt.driver.ComputeDriver.cleanup` for more
        information.
        """
        container = self.client.containers.get(instance.name)
        container.restart(force=True, wait=True)

    def get_console_output(self, context, instance):
        """Get the output of the container console.

        See `nova.virt.driver.ComputeDriver.get_console_output` for more
        information.
        """
        instance_attrs = common.InstanceAttributes(instance)
        console_path = instance_attrs.console_path
        if not os.path.exists(console_path):
            return ''
        uid = pwd.getpwuid(os.getuid()).pw_uid
        utils.execute(
            'chown', '%s:%s' % (uid, uid), console_path, run_as_root=True)
        utils.execute(
            'chmod', '755', instance_attrs.container_path, run_as_root=True)
        with open(console_path, 'rb') as f:
            log_data, _ = utils.last_bytes(f, MAX_CONSOLE_BYTES)
            return log_data

    def get_host_ip_addr(self):
        return CONF.my_ip

    def attach_volume(self, context, connection_info, instance, mountpoint,
                      disk_bus=None, device_type=None, encryption=None):
        """Attach block device to a nova instance.

        Attaching a block device to a container requires a couple of steps.
        First os_brick connects the cinder volume to the host. Next,
        the block device is added to the containers profile. Next, the
        apparmor profile for the container is updated to allow mounting
        'ext4' block devices. Finally, the profile is saved.

        The block device must be formatted as ext4 in order to mount
        the block device inside the container.

        See `nova.virt.driver.ComputeDriver.attach_volume' for
        more information/
        """
        profile = self.client.profiles.get(instance.name)

        device_info = self.storage_driver.connect_volume(
            connection_info['data'])
        disk = os.stat(os.path.realpath(device_info['path']))
        vol_id = connection_info['data']['volume_id']

        disk_device = {
            vol_id: {
                'path': mountpoint,
                'major': '%s' % os.major(disk.st_rdev),
                'minor': '%s' % os.minor(disk.st_rdev),
                'type': 'unix-block'
            }
        }

        profile.devices.update(disk_device)
        # XXX zulcss (10 Jul 2016) - fused is currently not supported.
        profile.config.update({'raw.apparmor': 'mount fstype=ext4,'})
        profile.save()

    def detach_volume(self, connection_info, instance, mountpoint,
                      encryption=None):
        """Detach block device from a nova instance.

        First the volume id is deleted from the profile, and the
        profile is saved. The os-brick disconnects the volume
        from the host.

        See `nova.virt.driver.Computedriver.detach_volume` for
        more information.
        """
        profile = self.client.profiles.get(instance.name)
        vol_id = connection_info['data']['volume_id']
        if vol_id in profile.devices:
            del profile.devices[vol_id]
            profile.save()

        self.storage_driver.disconnect_volume(connection_info['data'], None)

    def attach_interface(self, instance, image_meta, vif):
        self.vif_driver.plug(instance, vif)
        self.firewall_driver.setup_basic_filtering(instance, vif)

        profile = self.client.profiles.get(instance.name)

        interfaces = []
        for key, val in profile.devices.items():
            if key.startswith('eth'):
                interfaces.append(key)
        net_device = 'eth{}'.format(len(interfaces))

        network_config = lxd_vif.get_config(vif)
        if 'bridge' in network_config:
            config_update = {
                net_device: {
                    'nictype': 'bridged',
                    'hwaddr': vif['address'],
                    'parent': network_config['bridge'],
                    'type': 'nic',
                }
            }
        else:
            config_update = {
                net_device: {
                    'nictype': 'p2p',
                    'hwaddr': vif['address'],
                    'type': 'nic',
                }
            }

        profile.devices.update(config_update)
        profile.save(wait=True)

    def detach_interface(self, instance, vif):
        self.vif_driver.unplug(instance, vif)

        profile = self.client.profiles.get(instance.name)
        to_remove = None
        for key, val in profile.devices.items():
            if val.get('hwaddr') == vif['address']:
                to_remove = key
                break
        del profile.devices[to_remove]
        profile.save(wait=True)

    def migrate_disk_and_power_off(
            self, context, instance, dest, _flavor, network_info,
            block_device_info=None, timeout=0, retry_interval=0):

        if CONF.my_ip == dest:
            # Make sure that the profile for the container is up-to-date to
            # the actual state of the container.
            flavor.to_profile(
                self.client, instance, network_info, block_device_info,
                update=True)
        container = self.client.containers.get(instance.name)
        container.stop(wait=True)
        return ''

    def snapshot(self, context, instance, image_id, update_task_state):
        lock_path = str(os.path.join(CONF.instances_path, 'locks'))

        with lockutils.lock(
                lock_path, external=True,
                lock_file_prefix=('lxd-snapshot-%s' % instance.name)):

            update_task_state(task_state=task_states.IMAGE_PENDING_UPLOAD)

            container = self.client.containers.get(instance.name)
            if container.status != 'Stopped':
                container.stop(wait=True)
            image = container.publish(wait=True)
            container.start(wait=True)

            update_task_state(
                task_state=task_states.IMAGE_UPLOADING,
                expected_state=task_states.IMAGE_PENDING_UPLOAD)

            snapshot = IMAGE_API.get(context, image_id)
            data = image.export()
            image_meta = {'name': snapshot['name'],
                          'disk_format': 'raw',
                          'container_format': 'bare'}
            IMAGE_API.update(context, image_id, image_meta, data)

    def pause(self, instance):
        """Pause container.

        See `nova.virt.driver.ComputeDriver.pause` for more
        information.
        """
        container = self.client.containers.get(instance.name)
        container.freeze(wait=True)

    def unpause(self, instance):
        """Unpause container.

        See `nova.virt.driver.ComputeDriver.unpause` for more
        information.
        """
        container = self.client.containers.get(instance.name)
        container.unfreeze(wait=True)

    def suspend(self, context, instance):
        """Suspend container.

        See `nova.virt.driver.ComputeDriver.suspend` for more
        information.
        """
        self.pause(instance)

    def resume(self, context, instance, network_info, block_device_info=None):
        """Resume container.

        See `nova.virt.driver.ComputeDriver.resume` for more
        information.
        """
        self.unpause(instance)

    def rescue(self, context, instance, network_info, image_meta,
               rescue_password):
        """Rescue a LXD container.

        Rescuing a instance requires a number of steps. First,
        the failed container is stopped. Next, '-rescue', is
        appended to the failed container's name, this is done
        so the container can be unrescued. The container's
        profile is updated with the rootfs of the
        failed container. Finally, a new container
        is created and started.

        See 'nova.virt.driver.ComputeDriver.rescue` for more
        information.
        """
        rescue = '%s-rescue' % instance.name

        container = self.client.containers.get(instance.name)
        container_rootfs = os.path.join(
            nova.conf.CONF.lxd.root_dir, 'containers', instance.name, 'rootfs')
        container.rename(rescue, wait=True)

        profile = self.client.profiles.get(instance.name)

        rescue_dir = {
            'rescue': {
                'source': container_rootfs,
                'path': '/mnt',
                'type': 'disk',
            }
        }
        profile.devices.update(rescue_dir)
        profile.save()

        container_config = {
            'name': instance.name,
            'profiles': [profile.name],
            'source': {
                'type': 'image',
                'alias': instance.image_ref,
            }
        }
        container = self.client.containers.create(
            container_config, wait=True)
        container.start(wait=True)

    def unrescue(self, instance, network_info):
        """Unrescue an instance.

        Unrescue a container that has previously been rescued.
        First the rescue containerisremoved. Next the rootfs
        of the defective container is removed from the profile.
        Finally the container is renamed and started.

        See 'nova.virt.drvier.ComputeDriver.unrescue` for more
        information.
        """
        rescue = '%s-rescue' % instance.name

        container = self.client.containers.get(instance.name)
        if container.status != 'Stopped':
            container.stop(wait=True)
        container.delete(wait=True)

        profile = self.client.profiles.get(instance.name)
        del profile.devices['rescue']
        profile.save()

        container = self.client.containers.get(rescue)
        container.rename(instance.name, wait=True)
        container.start(wait=True)

    def power_off(self, instance, timeout=0, retry_interval=0):
        """Power off an instance

        See 'nova.virt.drvier.ComputeDriver.power_off` for more
        information.
        """
        container = self.client.containers.get(instance.name)
        if container.status != 'Stopped':
            container.stop(wait=True)

    def power_on(self, context, instance, network_info,
                 block_device_info=None):
        """Power on an instance

        See 'nova.virt.drvier.ComputeDriver.power_on` for more
        information.
        """
        container = self.client.containers.get(instance.name)
        if container.status != 'Running':
            container.start(wait=True)

    def get_available_resource(self, nodename):
        """Aggregate all available system resources.

        See 'nova.virt.drvier.ComputeDriver.get_available_resource`
        for more information.
        """
        cpuinfo = _get_cpu_info()

        cpu_info = {
            'arch': platform.uname()[5],
            'features': cpuinfo.get('flags', 'unknown'),
            'model': cpuinfo.get('model name', 'unknown'),
            'topology': {
                'sockets': cpuinfo['socket(s)'],
                'cores': cpuinfo['core(s) per socket'],
                'threads': cpuinfo['thread(s) per core'],
            },
            'vendor': cpuinfo.get('vendor id', 'unknown'),
        }

        cpu_topology = cpu_info['topology']
        vcpus = (int(cpu_topology['cores']) *
                 int(cpu_topology['sockets']) *
                 int(cpu_topology['threads']))

        local_memory_info = _get_ram_usage()
        local_disk_info = _get_fs_info(CONF.lxd.root_dir)

        data = {
            'vcpus': vcpus,
            'memory_mb': local_memory_info['total'] / units.Mi,
            'memory_mb_used': local_memory_info['used'] / units.Mi,
            'local_gb': local_disk_info['total'] / units.Gi,
            'local_gb_used': local_disk_info['used'] / units.Gi,
            'vcpus_used': 0,
            'hypervisor_type': 'lxd',
            'hypervisor_version': '011',
            'cpu_info': jsonutils.dumps(cpu_info),
            'hypervisor_hostname': socket.gethostname(),
            'supported_instances': [
                (obj_fields.Architecture.I686, obj_fields.HVType.LXD,
                 obj_fields.VMMode.EXE),
                (obj_fields.Architecture.X86_64, obj_fields.HVType.LXD,
                 obj_fields.VMMode.EXE),
                (obj_fields.Architecture.I686, obj_fields.HVType.LXC,
                 obj_fields.VMMode.EXE),
                (obj_fields.Architecture.X86_64, obj_fields.HVType.LXC,
                 obj_fields.VMMode.EXE),
            ],
            'numa_topology': None,
        }

        return data

    def refresh_instance_security_rules(self, instance):
        return self.firewall_driver.refresh_instance_security_rules(
            instance)

    def ensure_filtering_rules_for_instance(self, instance, network_info):
        return self.firewall_driver.ensure_filtering_rules_for_instance(
            instance, network_info)

    def filter_defer_apply_on(self):
        return self.firewall_driver.filter_defer_apply_on()

    def filter_defer_apply_off(self):
        return self.firewall_driver.filter_defer_apply_off()

    def unfilter_instance(self, instance, network_info):
        return self.firewall_driver.unfilter_instance(
            instance, network_info)

    def get_host_uptime(self):
        out, err = utils.execute('env', 'LANG=C', 'uptime')
        return out

    def plug_vifs(self, instance, network_info):
        for vif in network_info:
            self.vif_driver.plug(instance, vif)

    def unplug_vifs(self, instance, network_info):
        for vif in network_info:
            self.vif_driver.unplug(instance, vif)

    def get_host_cpu_stats(self):
        return {
            'kernel': int(psutil.cpu_times()[2]),
            'idle': int(psutil.cpu_times()[3]),
            'user': int(psutil.cpu_times()[0]),
            'iowait': int(psutil.cpu_times()[4]),
            'frequency': _get_cpu_info().get('cpu mhz', 0)
        }

    def get_volume_connector(self, instance):
        return {'ip': CONF.my_block_storage_ip,
                'initiator': 'fake',
                'host': 'fakehost'}

    def get_available_nodes(self, refresh=False):
        hostname = socket.gethostname()
        return [hostname]

    # XXX: rockstar (5 July 2016) - The methods and code below this line
    # have not been through the cleanup process. We know the cleanup process
    # is complete when there is no more code below this comment, and the
    # comment can be removed.

    #
    # ComputeDriver implementation methods
    #
    def finish_migration(self, context, migration, instance, disk_info,
                         network_info, image_meta, resize_instance,
                         block_device_info=None, power_on=True):
        # Ensure that the instance directory exists
        instance_dir = common.InstanceAttributes(instance).instance_dir
        if not os.path.exists(instance_dir):
            fileutils.ensure_tree(instance_dir)

        # Step 1 - Setup the profile on the dest host
        flavor.to_profile(instance, network_info, block_device_info)

        # Step 2 - Open a websocket on the srct and and
        #          generate the container config
        self._migrate(migration['source_compute'], instance)

        # Step 3 - Start the network and container
        self.plug_vifs(instance, network_info)
        self.client.container.get(instance.name).start(wait=True)

    def confirm_migration(self, migration, instance, network_info):
        self.unplug_vifs(instance, network_info)

        self.client.profiles.get(instance.name).delete()
        self.client.containers.get(instance.name).delete(wait=True)

    def finish_revert_migration(self, context, instance, network_info,
                                block_device_info=None, power_on=True):
        self.client.containers.get(instance.name).start(wait=True)

    def pre_live_migration(self, context, instance, block_device_info,
                           network_info, disk_info, migrate_data=None):
        for vif in network_info:
            self.vif_driver.plug(instance, vif)
        self.firewall_driver.setup_basic_filtering(
            instance, network_info)
        self.firewall_driver.prepare_instance_filter(
            instance, network_info)
        self.firewall_driver.apply_instance_filter(
            instance, network_info)

        flavor.to_profile(instance, network_info, block_device_info)

    def live_migration(self, context, instance, dest,
                       post_method, recover_method, block_migration=False,
                       migrate_data=None):
        self._migrate(dest, instance)
        post_method(context, instance, dest, block_migration)

    def post_live_migration(self, context, instance, block_device_info,
                            migrate_data=None):
        self.client.containers.get(instance.name).delete(wait=True)

    def post_live_migration_at_source(self, context, instance, network_info):
        self.client.profiles.get(instance.name).delete()
        self.cleanup(context, instance, network_info)

    def check_can_live_migrate_destination(
            self, context, instance, src_compute_info, dst_compute_info,
            block_migration=False, disk_over_commit=False):
        try:
            self.client.containers.get(instance.name)
            raise exception.InstanceExists(name=instance.name)
        except lxd_exceptions.LXDAPIException as e:
            if e.response.status_code != 404:
                raise
        return LXDLiveMigrateData()

    def cleanup_live_migration_destination_check(
            self, context, dest_check_data):
        return

    def check_can_live_migrate_source(self, context, instance,
                                      dest_check_data, block_device_info=None):
        if not CONF.lxd.allow_live_migration:
            msg = _('Live migration is not enabled.')
            LOG.error(msg, instance=instance)
            raise exception.MigrationPreCheckError(reason=msg)
        return dest_check_data

    #
    # LXDDriver "private" implementation methods
    #
    # XXX: rockstar (21 Nov 2016) - The methods and code below this line
    # have not been through the cleanup process. We know the cleanup process
    # is complete when there is no more code below this comment, and the
    # comment can be removed.
    def _add_configdrive(self, context, instance,
                         injected_files, admin_password, network_info):
        """Create configdrive for the instance."""
        if CONF.config_drive_format != 'iso9660':
            raise exception.ConfigDriveUnsupportedFormat(
                format=CONF.config_drive_format)

        container = self.client.containers.get(instance.name)
        container_id_map = container.config[
            'volatile.last_state.idmap'].split(',')
        storage_id = container_id_map[2].split(':')[1]

        extra_md = {}
        if admin_password:
            extra_md['admin_pass'] = admin_password

        inst_md = instance_metadata.InstanceMetadata(
            instance, content=injected_files, extra_md=extra_md,
            network_info=network_info, request_context=context)

        iso_path = os.path.join(
            common.InstanceAttributes(instance).instance_dir,
            'configdrive.iso')

        with configdrive.ConfigDriveBuilder(instance_md=inst_md) as cdb:
            try:
                cdb.make_drive(iso_path)
            except processutils.ProcessExecutionError as e:
                with excutils.save_and_reraise_exception():
                    LOG.error(_LE('Creating config drive failed with '
                                  'error: %s'),
                              e, instance=instance)

        configdrive_dir = os.path.join(
            nova.conf.CONF.instances_path, instance.name, 'configdrive')
        if not os.path.exists(configdrive_dir):
            fileutils.ensure_tree(configdrive_dir)

        with utils.tempdir() as tmpdir:
            mounted = False
            try:
                _, err = utils.execute('mount',
                                       '-o',
                                       'loop,uid=%d,gid=%d' % (os.getuid(),
                                                               os.getgid()),
                                       iso_path, tmpdir,
                                       run_as_root=True)
                mounted = True

                # Copy and adjust the files from the ISO so that we
                # dont have the ISO mounted during the life cycle of the
                # instance and the directory can be removed once the instance
                # is terminated
                for ent in os.listdir(tmpdir):
                    shutil.copytree(os.path.join(tmpdir, ent),
                                    os.path.join(configdrive_dir, ent))
                    utils.execute('chmod', '-R', '775', configdrive_dir,
                                  run_as_root=True)
                    utils.execute('chown', '-R', storage_id, configdrive_dir,
                                  run_as_root=True)
            finally:
                if mounted:
                    utils.execute('umount', tmpdir, run_as_root=True)

        return configdrive_dir

    def _after_reboot(self):
        """Perform sync operation after host reboot."""
        context = nova.context.get_admin_context()
        instances = objects.InstanceList.get_by_host(
            context, self.host, expected_attrs=['info_cache', 'metadata'])

        for instance in instances:
            if (instance.vm_state != vm_states.STOPPED):
                continue
            try:
                network_info = self.network_api.get_instance_nw_info(
                    context, instance)
            except exception.InstanceNotFound:
                network_info = network_model.NetworkInfo()

            self.plug_vifs(instance, network_info)
            self.firewall_driver.setup_basic_filtering(instance, network_info)
            self.firewall_driver.prepare_instance_filter(
                instance, network_info)
            self.firewall_driver.apply_instance_filter(instance, network_info)

    def _migrate(self, source_host, instance):
        """Migrate an instance from source."""
        source_client = pylxd.Client(
            endpoint='https://{}'.format(source_host), verify=False)
        container = source_client.containers.get(instance.name)
        data = container.generate_migration_data()

        self.containers.create(data, wait=True)
