Nova-LXD VIF Design Notes
=========================

VIF plugging workflow
---------------------

Nova-LXD makes use of the os-vif interface plugging library to wire LXD
instances into underlying Neutron networking; however there are some
subtle differences between the Nova-Libvirt driver and the Nova-LXD driver
in terms of how the last mile wiring is done to the instances.

In the Nova-Libvirt driver, Libvirt is used to start the instance in a
paused state, which creates the required tap device and any required wiring
to bridges created in previous os-vif plugging events.

The concept of 'start-and-pause' does not exist in LXD, so the driver
creates a veth pair instead, allowing the last mile wiring to be created
in advance of the actual LXD container being created.

This allows Neutron to complete the underlying VIF plugging at which
point it will notify Nova and the Nova-LXD driver will create the LXD
container and wire the pre-created veth pair into its profile.

tap/tin veth pairs
------------------

The veth pair created to wire the LXD instance into the underlying Neutron
networking uses the tap and tin prefixes; the tap named device is present
on the host OS, allowing iptables based firewall rules to be applied as
they are for other virt drivers, and the tin named device is passed to
LXD as part of the container profile. LXD will rename this device
internally within the container to an ethNN style name.

The LXD profile devices for network interfaces are created as 'physical'
rather than 'bridged' network devices as the driver handles creation of
the veth pair, rather than LXD (as would happen with a bridged device).

LXD profile interface naming
----------------------------

The name of the interfaces in each containers LXD profile maps to the
devname provided by Neutron as part of VIF plugging - this will typically
be of the format tapXXXXXXX.  This allows for easier identification of
the interface during detachment events later in instance lifecycle.

Prior versions of the nova-lxd driver did not take this approach; interface
naming was not consistent depending on when the interface was attached. The
legacy code used to detach interfaces based on MAC address is used as a
fallback in the event that the new style device name is not found, supporting
upgraders from previous versions of the driver.

Supported Interface Types
-------------------------

The Nova-LXD driver has been validated with:

 - OpenvSwitch (ovs) hybrid bridge ports.
 - OpenvSwitch (ovs) standard ports.
 - Linuxbridge (bridge) ports
