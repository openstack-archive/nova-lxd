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

# nova-powervm directories
NOVA_COMPUTE_LXD_DIR=${NOVA_POWERVM_DIR:-${DEST}/nova-compute-lxd}
NOVA_COMPUTE_LXD_PLUGIN_DIR=$(readlink -f $(dirname ${BASH_SOURCE[0]}))

source $NOVA_COMPUTE_LXD_PLUGIN_DIR/nova-lxd-functions.sh

function pre_install_nova-compute-lxd() {
    # Install OS packages if necessary with "install_package ...".
    install_lxd
    install_pylxd
}

function install_nova-compute-lxd() {
    # Install the service.
    setup_develop $NOVA_COMPUTE_LXD_DIR
}

function configure_nova-compute-lxd() {
    # Configure the service.
    iniset $NOVA_CONF DEFAULT compute_driver nclxd.nova.virt.lxd.LXDDriver
}

function init_nova-compute-lxd() {
    # Initialize and start the service.
    :
}

function shutdown_nova-compute-lxd() {
    # Shut the service down.
    :
}

function cleanup_nova-compute-lxd() {
    # Cleanup the service.
    :
}

if is_service_enabled nova-compute-lxd; then

    if [[ "$1" == "stack" && "$2" == "pre-install" ]]; then
        # Set up system services
        echo_summary "Configuring system services nova-compute-lxd"
        pre_install_nova-compute-lxd

    elif [[ "$1" == "stack" && "$2" == "install" ]]; then
        # Perform installation of service source
        echo_summary "Installing nova-compute-lxd"
        install_nova-compute-lxd

    elif [[ "$1" == "stack" && "$2" == "post-config" ]]; then
        # Configure after the other layer 1 and 2 services have been configured
        echo_summary "Configuring nova-compute-lxd"
        configure_nova-compute-lxd

    elif [[ "$1" == "stack" && "$2" == "extra" ]]; then
        # Initialize and start the nova-compute-lxd service
        echo_summary "Initializing nova-compute-lxd"
        init_nova-compute-lxd
    fi

    if [[ "$1" == "unstack" ]]; then
        # Shut down nova-compute-lxd services
        # no-op
        shutdown_nova-compute-lxd
    fi

    if [[ "$1" == "clean" ]]; then
        # Remove state and transient data
        # Remember clean.sh first calls unstack.sh
        # no-op
        cleanup_nova-compute-lxd
    fi
fi
