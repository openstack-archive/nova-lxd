# nova-lxd [![Build Status](https://travis-ci.org/lxc/nova-lxd.svg?branch=master)](https://travis-ci.org/lxc/nova-lxd)

An OpenStack Compute driver for managing containers using LXD.

## nova-lxd on Devstack

For development purposes, nova-lxd provides a devstack plugin. To use it, just include the
following in your devstack `local.conf`:

```
[[local|localrc]]
enable_plugin nova-lxd https://git.openstack.org/openstack/nova-lxd
```

Change git repositories as needed (it's probably not very useful to point to the main
nova-lxd repo). If you have a local tree you'd like to use, you can symlink your tree to
`/opt/stack/nova-lxd` and do your development from there.

The devstack default images won't work with lxd, as lxd doesn't support them. Once your
stack is up and you've configured authentication against your devstack, do the following::

```
wget http://cloud-images.ubuntu.com/xenial/current/xenial-server-cloudimg-amd64-root.tar.gz
glance image-create --name xenial --disk-format raw --container-format bare --file xenial-server-cloudimg-amd64-root.tar.gz
```

You can test your configuration using the exercise scripts in devstack. For instance,

```
DEFAULT_IMAGE_NAME=xenial ./exercises/volumes.sh
```

Please note: the exercise scripts in devstack likely won't work, as they have requirements
for using the cirros images.

# Support and discussions

We use the LXC mailing-lists for developer and user discussions, you can
find and subscribe to those at: https://lists.linuxcontainers.org

If you prefer live discussions, some of us also hang out in
[#lxcontainers](http://webchat.freenode.net/?channels=#lxcontainers) on irc.freenode.net.

## Bug reports

Bug reports can be filed at https://bugs.launchpad.net/nova-lxd
