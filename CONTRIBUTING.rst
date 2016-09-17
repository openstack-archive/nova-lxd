Crash course in lxd setup
=========================

nova-lxd absolutely requires lxd, though its installation and configuration
is out of scope here. If you're running Ubuntu, here is the easy path
to a running lxd.

.. code-block: bash

   add-apt-repository ppa:ubuntu-lxc/lxd-git-master && sudo apt-get update
   apt-get -y install lxd
   usermod -G lxd ${your_username|stack}
   service lxd start

If you're currently logged in as the user you just added to lxd, you'll
need to log out and log back in again.


Using nova-lxd with devstack
============================

nova-lxd includes a plugin for use in devstack. If you'd like to run
devstack with nova-lxd, you'll want to add the following to `local.conf`:

.. code-block: bash

   enable_plugin nova-lxd https://git.openstack.org/openstack/nova-lxd

In this case, nova-lxd will run HEAD from master. You may want to point
this at your own fork. A final argument to `enable_plugin` can be used
to specify a git revision.

Configuration and installation of devstack is beyond the scope
of this document. Here's an example `local.conf` file that will
run the very minimum you`ll need for devstack.

.. code-block: bash

   [[local|localrc]]
   ADMIN_PASSWORD=password
   DATABASE_PASSWORD=$ADMIN_PASSWORD
   RABBIT_PASSWORD=$ADMIN_PASSWORD
   SERVICE_PASSWORD=$ADMIN_PASSWORD
   SERVICE_TOKEN=$ADMIN_PASSWORD

   disable_service cinder c-sch c-api c-vol
   disable_service n-net n-novnc
   disable_service horizon
   disable_service ironic ir-api ir-cond

   enable_service q-svc q-agt q-dhcp q-13 q-meta

   # Optional, to enable tempest configuration as part of devstack
   enable_service tempest

   enable_plugin nova-lxd https://git.openstack.org/openstack/nova-lxd

   # More often than not, stack.sh explodes trying to configure IPv6 support,
   # so let's just disable it for now.
   IP_VERSION=4

Once devstack is running, you'll want to add the lxd image to glance. You can
do this (as an admin) with:

.. code-block: bash

   wget http://cloud-images.ubuntu.com/trusty/current/trusty-server-cloudimg-amd64-root.tar.xz
   glance image-create --name lxd --container-format bare --disk-format raw \
      --visibility=public < trusty-server-cloudimg-amd64-root.tar.xz

To run the tempest tests, you can use:

.. code-block: bash

   /opt/stack/tempest/run_tempest.sh -N tempest.api.compute


Errata
======

Patches should be submitted to Openstack Gerrit via `git-review`.

Bugs should be filed on Launchpad:

   https://bugs.launchpad.net/nova-lxd

If you would like to contribute to the development of OpenStack,
you must follow the steps in this page:

   http://docs.openstack.org/infra/manual/developers.html

