#!/bin/bash

# Save trace setting
MY_XTRACE=$(set +o | grep xtrace)
set +o xtrace

# Defaults
# --------

# Set up base directories
NOVA_DIR=${NOVA_DIR:-$DEST/nova}
NOVA_CONF_DIR=${NOVA_CONF_DIR:-/etc/nova}
NOVA_CONF=${NOVA_CONF:-NOVA_CONF_DIR/nova.conf}

# Configure LXD storage backends
# Note Bug:1822182 - ZFS backend is broken for Rescue's so don't use it!
LXD_BACKEND_DRIVER=${LXD_BACKEND_DRIVER:-default}
LXD_DISK_IMAGE=${DATA_DIR}/lxd.img
LXD_ZFS_ZPOOL=devstack
LXD_LOOPBACK_DISK_SIZE=${LXD_LOOPBACK_DISK_SIZE:-8G}

# nova-lxd directories
NOVA_COMPUTE_LXD_DIR=${NOVA_COMPUTE_LXD_DIR:-${DEST}/nova-lxd}
NOVA_COMPUTE_LXD_PLUGIN_DIR=$(readlink -f $(dirname ${BASH_SOURCE[0]}))

# glance directories
GLANCE_CONF_DIR=${GLANCE_CONF_DIR:-/etc/glance}
GLANCE_API_CONF=$GLANCE_CONF_DIR/glance-api.conf

function pre_install_nova-lxd() {
    # Install OS packages if necessary with "install_package ...".
    echo_summary "Installing LXD"
    if is_ubuntu; then
        if [ "$DISTRO" == "trusty" ]; then
            sudo add-apt-repository -y ppa:ubuntu-lxc/lxd-stable
        fi
        if ! ( is_package_installed lxd ); then
            install_package lxd
        fi

        add_user_to_group $STACK_USER $LXD_GROUP

        if [ "$DISTRO" == "bionic" ]; then
            # install apparmor on the devstack image and restart lxd daemon
            # the devstack-gate image that is built lacks apparmor, but LXD
            # requires apparmor to work, so we add it back into the image.
            sudo apt install -y apparmor apparmor-profiles-extra apparmor-utils
            sudo systemctl restart lxd.service
        fi
    fi
}

function install_nova-lxd() {
    # Install the service.
    setup_develop $NOVA_COMPUTE_LXD_DIR
}

function configure_nova-lxd() {
    # Configure the service.
    iniset $NOVA_CONF DEFAULT compute_driver lxd.LXDDriver
    iniset $NOVA_CONF DEFAULT force_config_drive False

    if [ "$LXD_BACKEND_DRIVER" == "zfs" ]; then
        # For LXD 3 and upper we need pool name configured, see:
        # bug/1782329
        iniset $NOVA_CONF lxd pool $LXD_ZFS_ZPOOL
    fi
    if [ "$DISTRO-$LXD_BACKEND_DRIVER" == "bionic-default" ]; then
        # for LXD 3 we need to have a pool name configured, and for default
        # driver, it is 'default'
        iniset $NOVA_CONF lxd pool default
    fi

    if is_service_enabled glance; then
        iniset $GLANCE_API_CONF DEFAULT disk_formats "ami,ari,aki,vhd,raw,iso,qcow2,root-tar"
        iniset $GLANCE_API_CONF DEFAULT container_formats "ami,ari,aki,bare,ovf,tgz"
    fi

    # Install the rootwrap
    sudo install -o root -g root -m 644 $NOVA_COMPUTE_LXD_DIR/etc/nova/rootwrap.d/*.filters $NOVA_CONF_DIR/rootwrap.d
}

function init_nova-lxd() {
    # Initialize and start the service.

    mkdir -p $TOP_DIR/files

    # Download and install the cirros lxc image
    CIRROS_IMAGE_FILE=cirros-${CIRROS_VERSION}-${CIRROS_ARCH}-lxc.tar.gz
    if [ ! -f $TOP_DIR/files/$CIRROS_IMAGE_FILE ]; then
        wget --progress=dot:giga \
             -c http://download.cirros-cloud.net/${CIRROS_VERSION}/${CIRROS_IMAGE_FILE} \
             -O $TOP_DIR/files/${CIRROS_IMAGE_FILE}
    fi
    openstack --os-cloud=devstack-admin \
              --os-region-name="$REGION_NAME" image create "cirros-${CIRROS_VERSION}-${CIRROS_ARCH}-lxd" \
              --public --container-format bare \
              --disk-format raw < $TOP_DIR/files/cirros-${CIRROS_VERSION}-${CIRROS_ARCH}-lxc.tar.gz

    if is_service_enabled cinder; then
       # Enable user namespace for ext4, this has only been tested on xenial+
       echo Y | sudo tee /sys/module/ext4/parameters/userns_mounts
    fi
}

function test_config_nova-lxd() {
    # Configure tempest or other tests as required
    if is_service_enabled tempest; then
       TEMPEST_CONFIG=${TEMPEST_CONFIG:-$TEMPEST_DIR/etc/tempest.conf}
       TEMPEST_IMAGE=`openstack image list | grep cirros-${CIRROS_VERSION}-${CIRROS_ARCH}-lxd | awk {'print $2'}`
       TEMPEST_IMAGE_ALT=$TEMPEST_IMAGE
       iniset $TEMPEST_CONFIG image disk_formats "ami,ari,aki,vhd,raw,iso,root-tar"
       iniset $TEMPEST_CONFIG compute volume_device_name sdb
       # TODO(jamespage): Review and update
       iniset $TEMPEST_CONFIG compute-feature-enabled shelve False
       iniset $TEMPEST_CONFIG compute-feature-enabled resize False
       iniset $TEMPEST_CONFIG compute-feature-enabled config_drive False
       iniset $TEMPEST_CONFIG compute-feature-enabled attach_encrypted_volume False
       iniset $TEMPEST_CONFIG compute-feature-enabled vnc_console False
       iniset $TEMPEST_CONFIG compute image_ref $TEMPEST_IMAGE
       iniset $TEMPEST_CONFIG compute image_ref_alt $TEMPEST_IMAGE_ALT
       iniset $TEMPEST_CONFIG scenario img_file cirros-${CIRROS_VERSION}-${CIRROS_ARCH}-lxc.tar.gz
    fi
}

function configure_lxd_block() {
    echo_summary "Configure LXD storage backend."
    if is_ubuntu; then
        if [ "$LXD_BACKEND_DRIVER" == "default" ]; then
            if [ "$DISTRO" == "bionic" ]; then
                echo_summary " . Configuring default dir backend for bionic lxd"
                sudo lxd init --auto --storage-backend dir
            fi
        elif [ "$LXD_BACKEND_DRIVER" == "zfs" ]; then
            pool=`lxc profile device get default root pool 2>> /dev/null || :`
            if [ "$pool" != "$LXD_ZFS_ZPOOL" ]; then
                echo_summary " . Configuring ZFS backend"
                truncate -s $LXD_LOOPBACK_DISK_SIZE $LXD_DISK_IMAGE
                # TODO(sahid): switch to use snap
                sudo apt-get install -y zfsutils-linux
                lxd_dev=`sudo losetup --show -f ${LXD_DISK_IMAGE}`
                sudo lxd init --auto --storage-backend zfs --storage-pool $LXD_ZFS_ZPOOL \
                    --storage-create-device $lxd_dev
            else
                echo_summary " . ZFS backend already configured"
            fi
        fi
    fi
}

function shutdown_nova-lxd() {
    # Shut the service down.
    :
}

function cleanup_nova-lxd() {
    # Cleanup the service.
    if [ "$LXD_BACKEND_DRIVER" == "zfs" ]; then
        pool=`lxc profile device get default root pool 2>> /dev/null || :`
        if [ "$pool" == "$LXD_ZFS_ZPOOL" ]; then
            sudo lxc profile device remove default root
            sudo lxc storage delete $LXD_ZFS_ZPOOL
        fi
    fi
}

if is_service_enabled nova-lxd; then

    if [[ "$1" == "stack" && "$2" == "pre-install" ]]; then
        # Set up system services
        echo_summary "Configuring system services nova-lxd"
        pre_install_nova-lxd
        configure_lxd_block

    elif [[ "$1" == "stack" && "$2" == "install" ]]; then
        # Perform installation of service source
        echo_summary "Installing nova-lxd"
        install_nova-lxd

    elif [[ "$1" == "stack" && "$2" == "post-config" ]]; then
        # Configure after the other layer 1 and 2 services have been configured
        echo_summary "Configuring nova-lxd"
        configure_nova-lxd

    elif [[ "$1" == "stack" && "$2" == "extra" ]]; then
        # Initialize and start the nova-lxd service
        echo_summary "Initializing nova-lxd"
        init_nova-lxd

    elif [[ "$1" == "stack" && "$2" == "test-config" ]]; then
        # Configure any testing configuration
        echo_summary "Test configuration - nova-lxd"
        test_config_nova-lxd
    fi

    if [[ "$1" == "unstack" ]]; then
        # Shut down nova-lxd services
        # no-op
        shutdown_nova-lxd
    fi

    if [[ "$1" == "clean" ]]; then
        # Remove state and transient data
        # Remember clean.sh first calls unstack.sh
        # no-op
        cleanup_nova-lxd
    fi
fi
