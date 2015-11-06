====================
Enabling in Devstack
===================

1. Download DevStack:

   $ git clone https://git.openstack.org/openstack-dev/devstack /opt/stack/devstack

2. Modify DevStack's local.conf to pull in this project by adding:

   [[local|localrc]]
   enable_plugin nova-compute-lxd https://github.com/lxc/nova-compute-lxd

3. run stack.sh

