# Copyright 2011 Justin Santa Barbara
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

import os
import platform
import pwd
import shutil
import socket

from nova.api.metadata import base as instance_metadata
from nova.virt import configdrive
from nova import image
from nova import exception
from nova import i18n
from nova.virt import driver
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import fileutils
import pylxd
from pylxd import exceptions as lxd_exceptions
from nova.compute import utils as compute_utils

from nova.virt.lxd import config
from nova.virt.lxd import image as container_image
from nova.virt.lxd import migrate
from nova.virt.lxd import vif as lxd_vif
from nova.virt.lxd import session
from nova.virt.lxd import utils as container_utils

from nova.compute import arch
from nova.compute import hv_type
from nova.compute import vm_mode
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
    cfg.IntOpt('retry_interval',
               default=2,
               help='How often to retry in seconds when a'
                    'request does conflict'),
    cfg.BoolOpt('allow_live_migrate',
                default=False,
                help='Determine wheter to allow live migration'),
]

CONF = cfg.CONF
CONF.register_opts(lxd_opts, 'lxd')
LOG = logging.getLogger(__name__)
IMAGE_API = image.API()

MAX_CONSOLE_BYTES = 100 * units.Ki


class LXDDriver(driver.ComputeDriver):

    """LXD Lightervisor."""

    capabilities = {
        "has_imagecache": False,
        "supports_recreate": False,
        "supports_migrate_to_same_host": False,
        "supports_attach_interface": True
    }

    def __init__(self, virtapi):
        super(LXDDriver, self).__init__(virtapi)

        self.vif_driver = lxd_vif.LXDGenericDriver()

        self.config = config.LXDContainerConfig()
        self.container_migrate = migrate.LXDContainerMigrate()
        self.container_dir = container_utils.LXDContainerDirectories()
        self.image = container_image.LXDContainerImage()

        # The pylxd client, initialized with init_host
        self.client = None

        self.firewall_driver = firewall.load_driver(
            default='nova.virt.firewall.NoopFirewallDriver')

        # XXX: rockstar (1 Jul 2016) - This is temporary, until we can
        # switch to the newer pylxd api.
        self.session = session.LXDAPISession()
        self.lock_path = str(os.path.join(CONF.instances_path, 'locks'))

    def init_host(self, host):
        try:
            self.client = pylxd.Client()
            return True
        except lxd_exceptions.ClientConnectionFailed as e:
            msg = _('Unable to connect to LXD daemon: %s') % e
            raise exception.HostNotFound(msg)

    def get_info(self, instance):
        LOG.debug('get_info called for instance', instance=instance)
        try:
            container_state = self.session.container_state(instance)
            return hardware.InstanceInfo(state=container_state['state'],
                                         max_mem_kb=container_state['max_mem'],
                                         mem_kb=container_state['mem'],
                                         num_cpu=instance.flavor.vcpus,
                                         cpu_time_ns=0)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Failed to get container info'
                              ' for %(instance)s: %(ex)s'),
                          {'instance': instance.name, 'ex': ex},
                          instance=instance)

    def instance_exists(self, instance):
        return instance.name in self.list_instances()

    def plug_vifs(self, instance, network_info):
        """Plug VIFs into networks."""
        for vif in network_info:
            self.vif_driver.plug(instance, vif)
        self.firewall_driver.setup_basic_filtering(instance, network_info)
        self.firewall_driver.prepare_instance_filter(instance, network_info)
        self.firewall_driver.apply_instance_filter(instance, network_info)

    def unplug_vifs(self, instance, network_info):
        """Unplug VIFs from networks."""
        for vif in network_info:
            try:
                self.vif_driver.unplug(instance, vif)
            except exception.NovaException:
                pass
        self.firewall_driver.unfilter_instance(instance, network_info)

    def estimate_instance_overhead(self, instance_info):
        return {'memory_mb': 0}

    def list_instances(self):
        try:
            return [c.name for c in self.client.containers.all()]
        except lxd_exceptions.LXDAPIException as ex:
            msg = _('Failed to communicate with LXD API: %(reason)s') \
                % {'reason': ex}
            LOG.error(msg)
            raise exception.NovaException(msg)

    def list_instance_uuids(self):
        raise NotImplementedError()

    def spawn(self, context, instance, image_meta, injected_files,
              admin_password, network_info=None, block_device_info=None):
        msg = ('Spawning container '
               'network_info=%(network_info)s '
               'image_meta=%(image_meta)s '
               'instance=%(instance)s '
               'block_device_info=%(block_device_info)s' %
               {'network_info': network_info,
                'instance': instance,
                'image_meta': image_meta,
                'block_device_info': block_device_info})

        LOG.debug(msg, instance=instance)

        instance_name = instance.name

        if self.session.container_defined(instance_name, instance):
            raise exception.InstanceExists(name=instance.name)

        try:
            self.instance_dir = \
                self.container_dir.get_instance_dir(instance_name)
            if not os.path.exists(self.instance_dir):
                fileutils.ensure_tree(self.instance_dir)

            # Fetch the image from glance
            self.image.setup_image(context, instance, image_meta)

            # Plugin the network
            self.plug_vifs(instance, network_info)

            # Create the container profile
            container_profile = self.config.create_profile(instance,
                                                           network_info)
            self.session.profile_create(container_profile, instance)

            # Create the container
            container_config = {
                'name': instance_name,
                'profiles': [str(instance.name)],
                'source': self.config.get_container_source(instance),
                'devices': {}
            }
            self.session.container_init(
                container_config, instance)

            if configdrive.required_by(instance):
                self._add_configdrive(instance, injected_files)

            # Start the container
            self.session.container_start(instance_name, instance)

        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Faild to start container '
                              '%(instance)s: %(ex)s'),
                          {'instance': instance.name, 'ex': ex},
                          instance=instance)

    def _add_configdrive(self, instance, injected_files):
        """Configure the config drive for the container

        :param instance: nova instance object
        :param injected_files: instance injected files
        """
        LOG.debug('add_configdrive called for instance', instance=instance)

        extra_md = {}
        inst_md = instance_metadata.InstanceMetadata(instance,
                                                     content=injected_files,
                                                     extra_md=extra_md)
        # Create the ISO image so we can inject the contents of the ISO
        # into the container
        iso_path = os.path.join(self.instance_dir, 'configdirve.iso')
        with configdrive.ConfigDriveBuilder(instance_md=inst_md) as cdb:
            try:
                cdb.make_drive(iso_path)
            except Exception as e:
                with excutils.save_and_reraise_exception():
                    LOG.error(_LE('Creating config drive failed with error: '
                                  '%s'), e, instance=instance)

        # Copy the metadata info from the ISO into the container
        configdrive_dir = \
            self.container_dir.get_container_configdrive(instance.name)
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
                utils.execute('chown', '-R', '%s:%s'
                              % (self._uid_map('/etc/subuid').rstrip(),
                                 self._uid_map('/etc/subgid').rstrip()),
                              configdrive_dir, run_as_root=True)
            finally:
                if mounted:
                    utils.execute('umount', tmpdir, run_as_root=True)

    def destroy(self, context, instance, network_info, block_device_info=None,
                destroy_disks=True, migrate_data=None):
        LOG.debug('destroy called for instance', instance=instance)
        try:
            self.session.profile_delete(instance)
            self.session.container_destroy(instance.name,
                                           instance)
            self.cleanup(context, instance, network_info, block_device_info)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Failed to remove container'
                              ' for %(instance)s: %(ex)s'),
                          {'instance': instance.name, 'ex': ex},
                          instance=instance)

    def cleanup(self, context, instance, network_info, block_device_info=None,
                destroy_disks=True, migrate_data=None, destroy_vifs=True):
        LOG.debug('cleanup called for instance', instance=instance)
        try:
            if destroy_vifs:
                self.unplug_vifs(instance, network_info)

            name = pwd.getpwuid(os.getuid()).pw_name
            configdrive_dir = \
                self.container_dir.get_container_configdrive(instance.name)
            if os.path.exists(configdrive_dir):
                utils.execute('chown', '-R', '%s:%s' % (name, name),
                              configdrive_dir, run_as_root=True)
                shutil.rmtree(configdrive_dir)

            container_dir = self.container_dir.get_instance_dir(instance.name)
            if os.path.exists(container_dir):
                shutil.rmtree(container_dir)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.exception(_LE('Container cleanup failed for '
                                  '%(instance)s: %(ex)s'),
                              {'instance': instance.name,
                               'ex': ex}, instance=instance)

    def reboot(self, context, instance, network_info, reboot_type,
               block_device_info=None, bad_volumes_callback=None):
        LOG.debug('reboot called for instance', instance=instance)
        try:
            self.session.container_reboot(instance)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.exception(_LE('Container reboot failed for '
                                  '%(instance)s: %(ex)s'),
                              {'instance': instance.name,
                               'ex': ex}, instance=instance)

    def get_console_output(self, context, instance):
        LOG.debug('get_console_output called for instance', instance=instance)
        try:
            console_log = self.container_dir.get_console_path(instance.name)
            if not os.path.exists(console_log):
                return ""
            uid = pwd.getpwuid(os.getuid()).pw_uid
            utils.execute('chown', '%s:%s' % (uid, uid),
                          console_log, run_as_root=True)
            utils.execute('chmod', '755',
                          os.path.join(
                              self.container_dir.get_container_dir(
                                  instance.name), instance.name),
                          run_as_root=True)
            with open(console_log, 'rb') as fp:
                log_data, remaning = utils.last_bytes(fp,
                                                      MAX_CONSOLE_BYTES)
                return log_data
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Failed to get container output'
                              ' for %(instance)s: %(ex)s'),
                          {'instance': instance.name, 'ex': ex},
                          instance=instance)

    def get_diagnostics(self, instance):
        raise NotImplementedError()

    def get_instance_diagnostics(self, instance):
        raise NotImplementedError()

    def get_all_bw_counters(self, instances):
        raise NotImplementedError()

    def get_all_volume_usage(self, context, compute_host_bdms):
        raise NotImplementedError()

    def get_host_ip_addr(self):
        ips = compute_utils.get_machine_ips()
        if CONF.my_ip not in ips:
            LOG.warn(_LW('my_ip address (%(my_ip)s) was not found on '
                         'any of the interfaces: %(ifaces)s'),
                     {'my_ip': CONF.my_ip, 'ifaces': ", ".join(ips)})
        return CONF.my_ip

    def attach_volume(self, context, connection_info, instance, mountpoint,
                      disk_bus=None, device_type=None, encryption=None):
        raise NotImplementedError()

    def detach_volume(self, connection_info, instance, mountpoint,
                      encryption=None):
        raise NotImplementedError()

    def swap_volume(self, old_connection_info, new_connection_info,
                    instance, mountpoint, resize_to):
        raise NotImplementedError()

    def attach_interface(self, instance, image_meta, vif):
        LOG.debug('container_attach_interface called for instance',
                  instance=instance)
        try:
            self.vif_driver.plug(instance, vif)
            self.firewall_driver.setup_basic_filtering(instance, vif)

            container_config = self.config.create_container(instance)
            container_network = self.config.create_container_net_device(
                instance, vif)
            container_config['devices'].update(container_network)
            self.session.container_update(container_config, instance)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                self.vif_driver.unplug(instance, vif)
                LOG.error(_LE('Failed to configure network'
                              ' for %(instance)s: %(ex)s'),
                          {'instance': instance.name, 'ex': ex},
                          instance=instance)

    def detach_interface(self, instance, vif):
        LOG.debug('container_defatch_interface called for instance',
                  instance=instance)
        try:
            self.vif_driver.unplug(instance, vif)
        except exception.NovaException:
            pass

    def migrate_disk_and_power_off(self, context, instance, dest,
                                   flavor, network_info,
                                   block_device_info=None,
                                   timeout=0, retry_interval=0):
        return self.container_migrate.migrate_disk_and_power_off(
            context, instance, dest, flavor,
            network_info, block_device_info, timeout,
            retry_interval)

    def snapshot(self, context, instance, image_id, update_task_state):
        try:
            if not self.session.container_defined(instance.name, instance):
                raise exception.InstanceNotFound(instance_id=instance.name)

            with lockutils.lock(self.lock_path,
                                lock_file_prefix=('lxd-snapshot-%s' %
                                                  instance.name),
                                external=True):

                update_task_state(task_state=task_states.IMAGE_PENDING_UPLOAD)

                # We have to stop the container before we can publish the
                # image to the local store
                self.session.container_stop(instance.name,
                                            instance)
                fingerprint = self._save_lxd_image(instance,
                                                   image_id)
                self.session.container_start(instance.name, instance)

                update_task_state(task_state=task_states.IMAGE_UPLOADING,
                                  expected_state=task_states.IMAGE_PENDING_UPLOAD)  # noqa
                self._save_glance_image(context, instance, image_id,
                                        fingerprint)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Failed to create snapshot for %(instance)s: '
                              '%(ex)s'), {'instance': instance.name, 'ex': ex},
                          instance=instance)

    def post_interrupted_snapshot_cleanup(self, context, instance):
        pass

    def finish_migration(self, context, migration, instance, disk_info,
                         network_info, image_meta, resize_instance,
                         block_device_info=None, power_on=True):
        return self.container_migrate.finish_migration(
            context, migration, instance, disk_info,
            network_info, image_meta, resize_instance,
            block_device_info, power_on)

    def confirm_migration(self, migration, instance, network_info):
        return self.container_migrate.confirm_migration(migration,
                                                        instance,
                                                        network_info)

    def finish_revert_migration(self, context, instance, network_info,
                                block_device_info=None, power_on=True):
        return self.container_migrate.finish_revert_migration(
            context, instance, network_info, block_device_info,
            power_on)

    def pause(self, instance):
        LOG.debug('pause called for instance', instance=instance)
        try:
            self.session.container_pause(instance.name, instance)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Failed to pause container'
                              ' for %(instance)s: %(ex)s'),
                          {'instance': instance.name, 'ex': ex},
                          instance=instance)

    def unpause(self, instance):
        LOG.debug('unpause called for instance', instance=instance)
        try:
            self.session.container_unpause(instance.name, instance)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Failed to unpause container'
                              ' for %(instance)s: %(ex)s'),
                          {'instance': instance.name, 'ex': ex},
                          instance=instance)

    def suspend(self, context, instance):
        LOG.debug('suspend called for instance', instance=instance)
        try:
            self.session.container_pause(instance.name, instance)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.exception(_LE('Container suspend failed for '
                                  '%(instance)s: %(ex)s'),
                              {'instance': instance.name,
                               'ex': ex}, instance=instance)

    def resume(self, context, instance, network_info, block_device_info=None):
        LOG.debug('resume called for instance', instance=instance)
        try:
            self.session.container_unpause(instance.name, instance)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Failed to resume container'
                              ' for %(instance)s: %(ex)s'),
                          {'instance': instance.name, 'ex': ex},
                          instance=instance)

    def rescue(self, context, instance, network_info, image_meta,
               rescue_password):
        LOG.debug('rescue called for instance', instance=instance)
        try:
            # Step 1 - Stop the old container
            self.session.container_stop(instance.name, instance)

            # Step 2 - Rename the broken contianer to be rescued
            self.session.container_move(instance.name,
                                        {'name': '%s-backup' % instance.name},
                                        instance)

            # Step 3 - Re use the old instance object and confiugre
            #          the disk mount point and create a new container.
            container_config = self.config.create_container(instance)
            rescue_dir = self.container_dir.get_container_rescue(
                instance.name + '-backup')
            config = self.config.configure_disk_path(rescue_dir,
                                                     'mnt', 'rescue', instance)
            container_config['devices'].update(config)
            self.session.container_init(container_config, instance)

            # Step 4 - Start the rescue instance
            self.session.container_start(instance.name, instance)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.exception(_LE('Container rescue failed for '
                                  '%(instance)s: %(ex)s'),
                              {'instance': instance.name,
                               'ex': ex}, instance=instance)

    def unrescue(self, instance, network_info):
        LOG.debug('unrescue called for instance', instance=instance)
        try:
            # Step 1 - Destory the rescue instance.
            self.session.container_destroy(instance.name,
                                           instance)

            # Step 2 - Rename the backup container that
            #          the user was working on.
            self.session.container_move(instance.name + '-backup',
                                        {'name': instance.name},
                                        instance)

            # Step 3 - Start the old contianer
            self.session.container_start(instance.name, instance)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.exception(_LE('Container unrescue failed for '
                                  '%(instance)s: %(ex)s'),
                              {'instance': instance.name,
                               'ex': ex}, instance=instance)

    def power_off(self, instance, timeout=0, retry_interval=0):
        LOG.debug('power_off called for instance', instance=instance)
        try:
            self.session.container_stop(instance.name,
                                        instance)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Failed to power_off container'
                              ' for %(instance)s: %(ex)s'),
                          {'instance': instance.name, 'ex': ex},
                          instance=instance)

    def power_on(self, context, instance, network_info,
                 block_device_info=None):
        LOG.debug('power_on called for instance', instance=instance)
        try:
            self.session.container_start(instance.name, instance)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.exception(_LE('Container power off for '
                                  '%(instance)s: %(ex)s'),
                              {'instance': instance.name,
                               'ex': ex}, instance=instance)

    def soft_delete(self, instance):
        raise NotImplementedError()

    def get_available_resource(self, nodename):
        LOG.debug('In get_available_resource')

        local_cpu_info = self._get_cpuinfo()
        cpu_topology = local_cpu_info['topology']
        vcpus = (int(cpu_topology['cores']) *
                 int(cpu_topology['sockets']) *
                 int(cpu_topology['threads']))

        local_memory_info = self._get_memory_mb_usage()
        local_disk_info = self._get_fs_info(CONF.lxd.root_dir)

        data = {
            'vcpus': vcpus,
            'memory_mb': local_memory_info['total'] / units.Mi,
            'memory_mb_used': local_memory_info['used'] / units.Mi,
            'local_gb': local_disk_info['total'] / units.Gi,
            'local_gb_used': local_disk_info['used'] / units.Gi,
            'vcpus_used': 0,
            'hypervisor_type': 'lxd',
            'hypervisor_version': '011',
            'cpu_info': jsonutils.dumps(local_cpu_info),
            'hypervisor_hostname': socket.gethostname(),
            'supported_instances':
                [(arch.I686, hv_type.LXD, vm_mode.EXE),
                    (arch.X86_64, hv_type.LXD, vm_mode.EXE),
                    (arch.I686, hv_type.LXC, vm_mode.EXE),
                    (arch.X86_64, hv_type.LXC, vm_mode.EXE)],
            'numa_topology': None,
        }

        return data

    def pre_live_migration(self, context, instance, block_device_info,
                           network_info, disk_info, migrate_data=None):
        self.container_migrate.pre_live_migration(
            context, instance, block_device_info, network_info,
            disk_info, migrate_data)

    def live_migration(self, context, instance, dest,
                       post_method, recover_method, block_migration=False,
                       migrate_data=None):
        self.container_migrate.live_migration(
            context, instance, dest, post_method,
            recover_method, block_migration,
            migrate_data)

    def post_live_migration(self, context, instance, block_device_info,
                            migrate_data=None):
        self.container_migrate.post_live_migration(
            context, instance, block_device_info, migrate_data)

    def post_live_migration_at_destination(self, context, instance,
                                           network_info,
                                           block_migration=False,
                                           block_device_info=None):
        self.container_migrate.post_live_migration_at_destination(
            context, instance, network_info, block_migration,
            block_device_info)

    def check_instance_shared_storage_local(self, context, instance):
        raise NotImplementedError()

    def check_instance_shared_storage_remote(self, context, data):
        raise NotImplementedError()

    def check_instance_shared_storage_cleanup(self, context, data):
        pass

    def check_can_live_migrate_destination(self, context, instance,
                                           src_compute_info, dst_compute_info,
                                           block_migration=False,
                                           disk_over_commit=False):
        return self.container_migrate.check_can_live_migrate_destination(
            context, instance, src_compute_info, dst_compute_info,
            block_migration, disk_over_commit)

    def check_can_live_migrate_destination_cleanup(self, context,
                                                   dest_check_data):
        self.container_migrate.check_can_live_migrate_destination_cleanup(
            context, dest_check_data)

    def post_live_migration_at_source(self, context, instance, network_info):
        return self.container_migrate.post_live_migration_at_snurce(
            context, instance, network_info)

    def check_can_live_migrate_source(self, context, instance,
                                      dest_check_data, block_device_info=None):
        self.container_migrate.check_can_live_migrate_source(
            context, instance, dest_check_data,
            block_device_info
        )

    def get_instance_disk_info(self, instance,
                               block_device_info=None):
        raise NotImplementedError()

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

    def poll_rebooting_instances(self, timeout, instances):
        raise NotImplementedError()

    def host_power_action(self, action):
        raise NotImplementedError()

    def host_maintenance_mode(self, host, mode):
        raise NotImplementedError()

    def set_host_enabled(self, enabled):
        raise NotImplementedError()

    def get_host_uptime(self):
        out, err = utils.execute('env', 'LANG=C', 'uptime')
        return out

    def get_host_cpu_stats(self):
        cpuinfo = self._get_cpu_info()
        return {
            'kernel': int(psutil.cpu_times()[2]),
            'idle': int(psutil.cpu_times()[3]),
            'user': int(psutil.cpu_times()[0]),
            'iowait': int(psutil.cpu_times()[4]),
            'frequency': cpuinfo.get('cpu mhz', 0)
        }

    def block_stats(self, instance, disk_id):
        raise NotImplementedError()

    def deallocate_networks_on_reschedule(self, instance):
        """Does the driver want networks deallocated on reschedule?"""
        return False

    def macs_for_instance(self, instance):
        return None

    def manage_image_cache(self, context, all_instances):
        pass

    def add_to_aggregate(self, context, aggregate, host, **kwargs):
        raise NotImplementedError()

    def remove_from_aggregate(self, context, aggregate, host, **kwargs):
        raise NotImplementedError()

    def undo_aggregate_operation(self, context, op, aggregate,
                                 host, set_error=True):
        raise NotImplementedError()

    def get_volume_connector(self, instance):
        return {'ip': CONF.my_block_storage_ip,
                'initiator': 'fake',
                'host': 'fakehost'}

    def get_available_nodes(self, refresh=False):
        hostname = socket.gethostname()
        return [hostname]

    def node_is_available(self, nodename):
        if nodename in self.get_available_nodes():
            return True
        # Refresh and check again.
        return nodename in self.get_available_nodes(refresh=True)

    def get_per_instance_usage(self):
        return {}

    def instance_on_disk(self, instance):
        return False

    def volume_snapshot_create(self, context, instance, volume_id,
                               create_info):
        raise NotImplementedError()

    def volume_snapshot_delete(self, context, instance, volume_id,
                               snapshot_id, delete_info):
        raise NotImplementedError()

    def quiesce(self, context, instance, image_meta):
        raise NotImplementedError()

    def unquiesce(self, context, instance, image_meta):
        raise NotImplementedError()

    # Private methods

    def _get_fs_info(self, path):
        """Get free/used/total space info for a filesystem

        :param path: Any dirent on the filesystem
        :returns: A dict containing
              :free: How much space is free (in bytes)
              :used: How much space is used (in bytes)
              :total: How big the filesytem is (in bytes)
        """
        hddinfo = os.statvfs(path)
        total = hddinfo.f_blocks * hddinfo.f_bsize
        available = hddinfo.f_bavail * hddinfo.f_bsize
        used = total - available
        return {'total': total,
                'available': available,
                'used': used}

    def _get_memory_mb_usage(self):
        """Get the used memory size(MB) of the host.

        :returns: the total usage of memory(MB)
        """

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

    def _get_cpuinfo(self):
        cpuinfo = self._get_cpu_info()

        cpu_info = dict()

        cpu_info['arch'] = platform.uname()[5]
        cpu_info['model'] = cpuinfo.get('model name', 'unknown')
        cpu_info['vendor'] = cpuinfo.get('vendor id', 'unknown')

        topology = dict()
        topology['sockets'] = cpuinfo.get('socket(s)', 1)
        topology['cores'] = cpuinfo.get('core(s) per socket', 1)
        topology['threads'] = cpuinfo.get('thread(s) per core', 1)
        cpu_info['topology'] = topology
        cpu_info['features'] = cpuinfo.get('flags', 'unknown')

        return cpu_info

    def _get_cpu_info(self):
        '''Parse the output of lscpu.'''
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

    def _save_lxd_image(self, instance, image_id):
        """Creates an LXD image from the LXD continaer

        """
        LOG.debug('_save_lxd_image called for instance', instance=instance)

        fingerprint = None
        try:
            # Publish the snapshot to the local LXD image store
            container_snapshot = {
                "properties": {},
                "public": False,
                "source": {
                    "name": instance.name,
                    "type": "container"
                }
            }
            (state, data) = self.session.container_publish(container_snapshot,
                                                           instance)
            event_id = data.get('operation')
            self.session.wait_for_snapshot(event_id, instance)

            # Image has been create but the fingerprint is buried deep
            # in the metadata when the snapshot is complete
            (state, data) = self.session.operation_info(event_id, instance)
            fingerprint = data['metadata']['metadata']['fingerprint']
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Failed to publish snapshot for %(instance)s: '
                              '%(ex)s'), {'instance': instance.name,
                                          'ex': ex}, instance=instance)

        try:
            # Set the alias for the LXD image
            alias_config = {
                'name': image_id,
                'target': fingerprint
            }
            self.session.create_alias(alias_config, instance)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Failed to create alias for %(instance)s: '
                              '%(ex)s'), {'instance': instance.name,
                                          'ex': ex}, instance=instance)

        return fingerprint

    def _save_glance_image(self, context, instance, image_id, fingerprint):
        LOG.debug('_save_glance_image called for instance', instance=instance)

        try:
            snapshot = IMAGE_API.get(context, image_id)
            data = self.session.container_export(fingerprint, instance)
            image_meta = {'name': snapshot['name'],
                          'disk_format': 'raw'}
            IMAGE_API.update(context, image_id, image_meta, data)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Failed to upload image to glance for '
                              '%(instance)s:  %(ex)s'),
                          {'instance': instance.name, 'ex': ex},
                          instance=instance)

    def _uid_map(self, subuid_f):
        LOG.debug('Checking for subuid')

        line = None
        with open(subuid_f, 'r') as fp:
            name = pwd.getpwuid(os.getuid()).pw_name
            for cline in fp:
                if cline.startswith(name + ":"):
                    line = cline
                    break
            if line is None:
                raise ValueError("%s not found in %s" % (name, subuid_f))
            toks = line.split(":")
            return toks[1]
