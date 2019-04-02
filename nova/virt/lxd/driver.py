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

import errno
import io
import os
import platform
import pwd
import shutil
import socket
import tarfile
import tempfile
import hashlib

import eventlet
import nova.conf
import nova.context
from contextlib import closing

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

lxd_opts = [
    cfg.StrOpt('root_dir',
               default='/var/lib/lxd/',
               help='Default LXD directory'),
    cfg.StrOpt('pool',
               default=None,
               help='LXD Storage pool to use with LXD >= 2.9'),
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


def _last_bytes(file_like_object, num):
    """Return num bytes from the end of the file, and remaning byte count.

    :param file_like_object: The file to read
    :param num: The number of bytes to return

    :returns: (data, remaining)
    """

    try:
        file_like_object.seek(-num, os.SEEK_END)
    except IOError as e:
        # seek() fails with EINVAL when trying to go before the start of
        # the file. It means that num is larger than the file size, so
        # just go to the start.
        if e.errno == errno.EINVAL:
            file_like_object.seek(0, os.SEEK_SET)
        else:
            raise

    remaining = file_like_object.tell()
    return (file_like_object.read(), remaining)


def _neutron_failed_callback(event_name, instance):
    LOG.error("Neutron Reported failure on event "
              "{event} for instance {uuid}"
              .format(event=event_name, uuid=instance.name),
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
        msg = _("Unable to parse lscpu output.")
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


def _get_zpool_info(pool_or_dataset):
    """Get the free/used/total diskspace in a zfs pool or dataset.
    A dataset is distinguished by having a '/' in the string.

    :param pool_or_dataset: The string name of the pool or dataset
    :type pool_or_dataset: str
    :returns: dictionary with keys 'total', 'available', 'used'
    :rtype: Dict[str, int]
    :raises: :class:`exception.NovaException`
    :raises: :class:`oslo.concurrency.PorcessExecutionError`
    :raises: :class:`OSError`
    """
    def _get_zfs_attribute(cmd, attribute):
        value, err = utils.execute(cmd, 'list',
                                   '-o', attribute,
                                   '-H',
                                   '-p',
                                   pool_or_dataset,
                                   run_as_root=True)
        if err:
            msg = _("Unable to parse zfs output.")
            raise exception.NovaException(msg)
        value = int(value.strip())
        return value

    if '/' in pool_or_dataset:
        # it's a dataset:
        # for zfs datasets we only have 'available' and 'used' and so need to
        # construct the total from available and used.
        used = _get_zfs_attribute('zfs', 'used')
        available = _get_zfs_attribute('zfs', 'available')
        total = available + used
    else:
        # otherwise it's a zpool
        total = _get_zfs_attribute('zpool', 'size')
        used = _get_zfs_attribute('zpool', 'alloc')
        available = _get_zfs_attribute('zpool', 'free')
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

        # NOTE(jamespage): Re-query by image_ref to ensure
        #                  that another process did not
        #                  sneak infront of this one and create
        #                  the same image already.
        try:
            client.images.get_by_alias(image_ref)
            return
        except lxd_exceptions.LXDAPIException as e:
            if e.response.status_code != 404:
                raise

        try:
            ifd, image_file = tempfile.mkstemp()
            mfd, manifest_file = tempfile.mkstemp()

            image = IMAGE_API.get(context, image_ref)
            if image.get('disk_format') not in ACCEPTABLE_IMAGE_FORMATS:
                raise exception.ImageUnacceptable(
                    image_id=image_ref, reason=_("Bad image format"))
            IMAGE_API.download(context, image_ref, dest_path=image_file)

            # It is possible that LXD already have the same image
            # but NOT aliased as result of previous publish/export operation
            # (snapshot from openstack).
            # In that case attempt to add it again
            # (implicitly via instance launch from affected image) will produce
            # LXD error - "Image with same fingerprint already exists".
            # Error does not have unique identifier to handle it we calculate
            # fingerprint of image as LXD do it and check if LXD already have
            # image with such fingerprint.
            # If any we will add alias to this image and will not re-import it
            def add_alias():

                def lxdimage_fingerprint():
                    def sha256_file():
                        sha256 = hashlib.sha256()
                        with closing(open(image_file, 'rb')) as f:
                            for block in iter(lambda: f.read(65536), b''):
                                sha256.update(block)
                        return sha256.hexdigest()

                    return sha256_file()

                fingerprint = lxdimage_fingerprint()
                if client.images.exists(fingerprint):
                    LOG.info("Image with fingerprint {fingerprint} already "
                             "exists but not accessible by alias {alias}, "
                             "add alias"
                             .format(fingerprint=fingerprint, alias=image_ref))
                    lxdimage = client.images.get(fingerprint)
                    lxdimage.add_alias(image_ref, '')
                    return True

                return False

            if add_alias():
                return

            # up2date LXD publish/export operations produce images which
            # already contains /rootfs and metdata.yaml in exported file.
            # We should not pass metdata explicitly in that case as imported
            # image will be unusable bacause LXD will think that it containts
            # rootfs and will not extract embedded /rootfs properly.
            # Try to detect if image content already has metadata and not pass
            # explicit metadata in that case
            def imagefile_has_metadata(image_file):
                try:
                    with closing(tarfile.TarFile.open(
                        name=image_file, mode='r:*')) as tf:
                        try:
                            tf.getmember('metadata.yaml')
                            return True
                        except KeyError:
                            pass
                except tarfile.ReadError:
                    pass
                return False

            if imagefile_has_metadata(image_file):
                LOG.info("Image {alias} already has metadata, "
                         "skipping metadata injection..."
                         .format(alias=image_ref))
                with open(image_file, 'rb') as image:
                    image = client.images.create(image, wait=True)
            else:
                metadata = {
                    'architecture': image.get(
                        'hw_architecture',
                        obj_fields.Architecture.from_host()),
                    'creation_date': int(os.stat(image_file).st_ctime)}
                metadata_yaml = jsonutils.dumps(
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
                            image, metadata=manifest,
                            wait=True)

            image.add_alias(image_ref, '')

        finally:
            os.close(ifd)
            os.close(mfd)
            os.unlink(image_file)
            os.unlink(manifest_file)


def brick_get_connector_properties(multipath=False, enforce_multipath=False):
    """Wrapper to automatically set root_helper in brick calls.
    :param multipath: A boolean indicating whether the connector can
                      support multipath.
    :param enforce_multipath: If True, it raises exception when multipath=True
                              is specified but multipathd is not running.
                              If False, it falls back to multipath=False
                              when multipathd is not running.
    """

    root_helper = utils.get_root_helper()
    return connector.get_connector_properties(root_helper,
                                              CONF.my_ip,
                                              multipath,
                                              enforce_multipath)


def brick_get_connector(protocol, driver=None,
                        use_multipath=False,
                        device_scan_attempts=3,
                        *args, **kwargs):
    """Wrapper to get a brick connector object.
    This automatically populates the required protocol as well
    as the root_helper needed to execute commands.
    """

    root_helper = utils.get_root_helper()
    if protocol.upper() == "RBD":
        kwargs['do_local_attach'] = True
    return connector.InitiatorConnector.factory(
        protocol, root_helper,
        driver=driver,
        use_multipath=use_multipath,
        device_scan_attempts=device_scan_attempts,
        *args, **kwargs)


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
        "supports_attach_interface": True,
        "supports_multiattach": False,
    }

    def __init__(self, virtapi):
        super(LXDDriver, self).__init__(virtapi)

        self.client = None  # Initialized by init_host
        self.host = NOVA_CONF.host
        self.network_api = network.API()
        self.vif_driver = lxd_vif.LXDGenericVifDriver()
        self.firewall_driver = firewall.load_driver(
            default='nova.virt.firewall.NoopFirewallDriver')

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
            msg = _("Unable to connect to LXD daemon: {}").format(e)
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
        try:
            container = self.client.containers.get(instance.name)
        except lxd_exceptions.NotFound:
            raise exception.InstanceNotFound(instance_id=instance.uuid)

        state = container.state()
        return hardware.InstanceInfo(
            state=_get_power_state(state.status_code))

    def list_instances(self):
        """Return a list of all instance names."""
        return [c.name for c in self.client.containers.all()]

    def spawn(self, context, instance, image_meta, injected_files,
              admin_password, allocations, network_info=None,
              block_device_info=None):
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
                LOG.warn("Timeout waiting for vif plugging callback for "
                         "instance {uuid}"
                         .format(uuid=instance['name']))
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
                    'path': '/config-drive',
                    'source': configdrive_path,
                    'type': 'disk',
                    'readonly': 'True',
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
        except lxd_exceptions.LXDAPIException:
            with excutils.save_and_reraise_exception():
                try:
                    self.cleanup(
                        context, instance, network_info, block_device_info)
                except Exception as e:
                    LOG.warn('The cleanup process failed with: %s. This '
                             'error may or not may be relevant', e)

    def destroy(self, context, instance, network_info, block_device_info=None,
                destroy_disks=True, migrate_data=None):
        """Destroy a running instance.

        Since the profile and the instance are created on `spawn`, it is
        safe to delete them together.

        See `nova.virt.driver.ComputeDriver.destroy` for more
        information.
        """
        lock_path = os.path.join(CONF.instances_path, 'locks')

        with lockutils.lock(
                lock_path, external=True,
                lock_file_prefix='lxd-container-{}'.format(instance.name)):
            # TODO(sahid): Each time we get a container we should
            # protect it by using a mutex.
            try:
                container = self.client.containers.get(instance.name)
                if container.status != 'Stopped':
                    container.stop(wait=True)
                container.delete(wait=True)
                if (instance.vm_state == vm_states.RESCUED):
                    rescued_container = self.client.containers.get(
                        '{}-rescue'.format(instance.name))
                    if rescued_container.status != 'Stopped':
                        rescued_container.stop(wait=True)
                    rescued_container.delete(wait=True)
            except lxd_exceptions.LXDAPIException as e:
                if e.response.status_code == 404:
                    LOG.warning("Failed to delete instance. "
                                "Container does not exist for {instance}."
                                .format(instance=instance.name))
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
        storage.detach_ephemeral(self.client,
                                 block_device_info,
                                 lxd_config,
                                 instance)

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
                LOG.warning("Failed to delete instance. "
                            "Profile does not exist for {instance}."
                            .format(instance=instance.name))
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
            log_data, _ = _last_bytes(f, MAX_CONSOLE_BYTES)
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
        protocol = connection_info['driver_volume_type']
        storage_driver = brick_get_connector(protocol)
        device_info = storage_driver.connect_volume(
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

    def detach_volume(self, context, connection_info, instance, mountpoint,
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

        protocol = connection_info['driver_volume_type']
        storage_driver = brick_get_connector(protocol)
        storage_driver.disconnect_volume(connection_info['data'], None)

    def attach_interface(self, context, instance, image_meta, vif):
        self.vif_driver.plug(instance, vif)
        self.firewall_driver.setup_basic_filtering(instance, vif)

        profile = self.client.profiles.get(instance.name)

        net_device = lxd_vif.get_vif_devname(vif)
        config_update = {
            net_device: {
                'nictype': 'physical',
                'hwaddr': vif['address'],
                'parent': lxd_vif.get_vif_internal_devname(vif),
                'type': 'nic',
            }
        }

        profile.devices.update(config_update)
        profile.save(wait=True)

    def detach_interface(self, context, instance, vif):
        try:
            profile = self.client.profiles.get(instance.name)
            devname = lxd_vif.get_vif_devname(vif)

            # NOTE(jamespage): Attempt to remove device using
            #                  new style tap naming
            if devname in profile.devices:
                del profile.devices[devname]
                profile.save(wait=True)
            else:
                # NOTE(jamespage): For upgrades, scan devices
                #                  and attempt to identify
                #                  using mac address as the
                #                  device will *not* have a
                #                  consistent name
                for key, val in profile.devices.items():
                    if val.get('hwaddr') == vif['address']:
                        del profile.devices[key]
                        profile.save(wait=True)
                        break
        except lxd_exceptions.NotFound:
            # This method is called when an instance get destroyed. It
            # could happen that Nova to receive an event
            # "vif-delete-event" after the instance is destroyed which
            # result the lxd profile not exist.
            LOG.debug("lxd profile for instance {instance} does not exist. "
                      "The instance probably got destroyed before this method "
                      "got called.".format(instance=instance.name))

        self.vif_driver.unplug(instance, vif)

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
                lock_file_prefix='lxd-container-{}'.format(instance.name)):

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

    def resume_state_on_host_boot(self, context, instance, network_info,
                                  block_device_info=None):
        """resume guest state when a host is booted."""
        try:
            state = self.get_info(instance).state
            ignored_states = (power_state.RUNNING,
                              power_state.SUSPENDED,
                              power_state.NOSTATE,
                              power_state.PAUSED)

            if state in ignored_states:
                return

            self.power_on(context, instance, network_info, block_device_info)
        except (exception.InternalError, exception.InstanceNotFound):
            pass

    def rescue(self, context, instance, network_info, image_meta,
               rescue_password):
        """Rescue a LXD container.

        From the perspective of nova, rescuing a instance requires a number of
        steps. First, the failed container is stopped, and then this method is
        called.

        So the original container is already stopped, and thus, next,
        '-rescue', is appended to the failed container's name, this is done so
        the container can be unrescued. The container's profile is updated with
        the rootfs of the failed container. Finally, a new container is created
        and started.

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

        lxd_config = self.client.host_info

        # NOTE(jamespage): ZFS storage report is very LXD 2.0.x
        #                  centric and will need to be updated
        #                  to support LXD storage pools
        storage_driver = lxd_config['environment']['storage']
        if storage_driver == 'zfs':
            # NOTE(ajkavanagh) - BUG/1782329 - this is temporary until storage
            # pools is implemented.  LXD 3 removed the storage.zfs_pool_name
            # key from the config.  So, if it fails, we need to grab the
            # configured storage pool and use that as the name instead.
            try:
                pool_name = lxd_config['config']['storage.zfs_pool_name']
            except KeyError:
                pool_name = CONF.lxd.pool
            local_disk_info = _get_zpool_info(pool_name)
        else:
            local_disk_info = _get_fs_info(CONF.lxd.root_dir)

        data = {
            'vcpus': vcpus,
            'memory_mb': local_memory_info['total'] // units.Mi,
            'memory_mb_used': local_memory_info['used'] // units.Mi,
            'local_gb': local_disk_info['total'] // units.Gi,
            'local_gb_used': local_disk_info['used'] // units.Gi,
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
        flavor.to_profile(self.client,
                          instance, network_info, block_device_info)

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

        flavor.to_profile(self.client,
                          instance, network_info, block_device_info)

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
            msg = _("Live migration is not enabled.")
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
        storage_id = 0
        """
        Determine UID shift used for container uid mapping
        Sample JSON config from LXD
        {
            "volatile.apply_template": "create",
            ...
            "volatile.last_state.idmap": "[
                {
                \"Isuid\":true,
                \"Isgid\":false,
                \"Hostid\":100000,
                \"Nsid\":0,
                \"Maprange\":65536
                },
                {
                \"Isuid\":false,
                \"Isgid\":true,
                \"Hostid\":100000,
                \"Nsid\":0,
                \"Maprange\":65536
                }] ",
            "volatile.tap5fd6808a-7b.name": "eth0"
        }
        """
        container_id_map = jsonutils.loads(
            container.config['volatile.last_state.idmap'])
        uid_map = list(filter(lambda id_map: id_map.get("Isuid"),
                              container_id_map))
        if uid_map:
            storage_id = uid_map[0].get("Hostid", 0)
        else:
            # privileged containers does not have uid/gid mapping
            # LXD API return nothing
            pass

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
                    LOG.error("Creating config drive failed with error: {}"
                              .format(e), instance=instance)

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
                utils.execute('chown', '-R',
                              '%s:%s' % (storage_id, storage_id),
                              configdrive_dir, run_as_root=True)
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
