#!/bin/bash

set -xe

env

NOVALXDDIR=$(readlink -f $(dirname $0)/../..)
INSTALLDIR=${INSTALLDIR:-/opt/stack}

cp $NOVALXDDIR/contrib/devstack/extras.d/70-lxd.sh $INSTALLDIR/devstack/extras.d
cp $NOVALXDDIR/contrib/devstack/lib/nova_plugins/hypervisor-lxd $INSTALLDIR/devstack/lib/nova_plugins/
cp $NOVALXDDIR/contrib/devstack/lib/lxd $INSTALLDIR/devstack/lib/lxd
cat - <<-EOF >> $INSTALLDIR/devstack/localrc
VIRT_DRIVER=lxd
export NON_STANDARD_REQS=1
EOF
