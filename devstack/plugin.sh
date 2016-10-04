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

# nova-lxd directories
NOVA_COMPUTE_LXD_DIR=${NOVA_COMPUTE_LXD_DIR:-${DEST}/nova-lxd}
NOVA_COMPUTE_LXD_PLUGIN_DIR=$(readlink -f $(dirname ${BASH_SOURCE[0]}))

# glance directories
GLANCE_CONF_DIR=${GLANCE_CONF_DIR:-/etc/glance}
GLANCE_API_CONF=$GLANCE_CONF_DIR/glance-api.conf

source $NOVA_COMPUTE_LXD_PLUGIN_DIR/nova-lxd-functions.sh

function pre_install_nova-lxd() {
    # Install OS packages if necessary with "install_package ...".
    install_lxd
    install_pylxd
}

function install_nova-lxd() {
    # Install the service.
    setup_develop $NOVA_COMPUTE_LXD_DIR
}

function configure_nova-lxd() {
    # Configure the service.
    iniset $NOVA_CONF DEFAULT compute_driver lxd.LXDDriver
    iniset $NOVA_CONF DEFAULT force_config_drive False

    iniset $GLANCE_API_CONF DEFAULT disk_formats "ami,ari,aki,vhd,raw,iso,qcow2,root-tar"
    iniset $GLANCE_API_CONF DEFAULT container_formats "ami,ari,aki,bare,ovf,tgz"

    # Install the rootwrap
    sudo install -o root -g root -m 644 $NOVA_COMPUTE_LXD_DIR/etc/nova/rootwrap.d/*.filters $NOVA_CONF_DIR/rootwrap.d
}

function init_nova-lxd() {
    # Initialize and start the service.
    
    mkdir -p mkdir -p $TOP_DIR/files

    # Download and install the root-tar image from xenial
    wget --progress=dot:giga -c https://cloud-images.ubuntu.com/xenial/current/xenial-server-cloudimg-amd64-root.tar.gz  \
         -O $TOP_DIR/files/xenial-server-cloudimg-amd64-root.tar.gz
    openstack --os-cloud=devstack-admin --os-region-name="$REGION_NAME" image create "ubuntu-16.04-lxd-root" \
         --public --container-format bare --disk-format raw < $TOP_DIR/files/xenial-server-cloudimg-amd64-root.tar.gz

    # Download and install the cirros lxc image
    wget --progress=dot:giga -c http://download.cirros-cloud.net/${CIRROS_VERSION}/cirros-${CIRROS_VERSION}-${CIRROS_ARCH}-lxc.tar.gz \
        -O $TOP_DIR/files/cirros-${CIRROS_VERSION}-${CIRROS_ARCH}-lxc.tar.gz
    openstack --os-cloud=devstack-admin --os-region-name="$REGION_NAME" image create "cirros-${CIRROS_VERSION}-${CIRROS_ARCH}-lxd" \
        --public --container-format bare --disk-format raw < $TOP_DIR/files/cirros-${CIRROS_VERSION}-${CIRROS_ARCH}-lxc.tar.gz
 
    if is_service_enabled tempest; then
       TEMPEST_CONFIG=${TEMPEST_CONFIG:-$TEMPEST_DIR/etc/tempest.conf}
       TEMPEST_IMAGE=`openstack image list | grep cirros-0.3.4-x86_64-lxd | awk {'print $2'}` 
       TEMPEST_IMAGE_ALT=`openstack image list | grep ubuntu-16.04-lxd-root | awk {'print $2'}`
       iniset $TEMPEST_CONFIG image disk_formats "ami,ari,aki,vhd,raw,iso,root-tar"
       iniset $TEMPEST_CONFIG compute volume_device_name sdb
       iniset $TEMPEST_CONFIG compute-feature-enabled shelve False
       iniset $TEMPEST_CONFIG compute-feature-enabled resize False
       iniset $TEMPEST_CONFIG compute-feature-enabled attach_encrypted_volume False
       iniset $TEMPEST_CONFIG compute image_ref $TEMPEST_IMAGE
       iniset $TEMPEST_CONFIG compute image_ref_alt $TEMPEST_IMAGE_ALT
       iniset $TEMPEST_CONFIG validation run_validation True
    fi

    if is_service_enabled cinder; then
       # Enable user namespace for ext4, this has only been tested on xenial+
       echo Y | sudo tee /sys/module/ext4/parameters/userns_mounts
    fi
}

function shutdown_nova-lxd() {
    # Shut the service down.
    :
}

function cleanup_nova-lxd() {
    # Cleanup the service.
    :
}

if is_service_enabled nova-lxd; then

    if [[ "$1" == "stack" && "$2" == "pre-install" ]]; then
        # Set up system services
        echo_summary "Configuring system services nova-lxd"
        pre_install_nova-lxd

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
