#!/bin/bash

# devstack/powervm-functions.sh
# Functions to control the installation and configuration of the PowerVM
# compute services

function install_lxd {
    echo_summary "Checing LXD installation"
    if is_ubuntu; then
        if [ "$DISTRO" == "trusty" ]; then
            sudo add-apt-repository -y ppa:ubuntu-lxc/lxd-stable
        fi
        if ! ( is_package_installed lxd ); then
            install_package lxd
        fi

        add_user_to_group $STACK_USER $LXD_GROUP
    fi
    echo_summary "Installing LXD"
}
