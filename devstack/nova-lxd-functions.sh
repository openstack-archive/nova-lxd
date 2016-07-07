#!/bin/bash

# devstack/powervm-functions.sh
# Functions to control the installation and configuration of the PowerVM
# compute services

GITREPO["pylxd"]=${PYLXD_REPO:-https://github.com/lxc/pylxd}
GITBRANCH["pylxd"]=${PYLXD_BRANCH:-master}
GITDIR["pylxd"]=$DEST/pylxd

function install_pylxd {
    # Install the latest pylxd from git
    echo_summary "Installing pylxd"
    git_clone_by_name pylxd
    if [ "$DISTRO" == "trusty" ]; then
        uninstall_package python-requests python-urllib3
    fi
    setup_dev_lib "pylxd"
    echo_summary "Pylxd install complete"
}

function cleanup_pylxd {
    echo_summary "Cleaning pylxd"
    rm -rf ${GITDIR["pylxd"]}
}

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
