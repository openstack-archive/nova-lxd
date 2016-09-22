Nova-LXD Exclusive Machine
==========================

As LXD is a system container format, it is possible to provision "bare metal"
machines with nova-lxd without exposing the kernel and firmware to the tenant.
This is done by means of host aggregates and flavor assignment. The instance
will fill the entirety of the host, and no other instances will be assigned
to it.

This document describes the method used to achieve this exclusive machine
scheduling. It is meant to serve as an example; the names of flavors and
aggregates may be named as desired.


Prerequisites
-------------

Exclusive machine scheduling requires two scheduler filters to be enabled in
`scheduler_default_filters` in `nova.conf`, namely
`AggregateInstanceExtraSpecsFilter` and `AggregateNumInstancesFilter`.

If juju was used to install and manage the openstack environment, the following
command will enable these filters::

    juju set nova-cloud-controller scheduler-default-filters="AggregateInstanceExtraSpecsFilter,AggregateNumInstancesFilter,RetryFilter,AvailabilityZoneFilter,CoreFilter,RamFilter,ComputeFilter,ComputeCapabilitiesFilter,ImagePropertiesFilter,ServerGroupAntiAffinityFilter,ServerGroupAffinityFilter"


Host Aggregate
--------------

Each host designed to be exclusively available to a single instance must be
added to a special host aggregate.

In this example, the following is a nova host listing::

    user@openstack$ nova host-list
    +------------+-----------+----------+
    | host_name  | service   | zone     |
    +------------+-----------+----------+
    | machine-9  | cert      | internal |
    | machine-9  | scheduler | internal |
    | machine-9  | conductor | internal |
    | machine-12 | compute   | nova     |
    | machine-11 | compute   | nova     |
    | machine-10 | compute   | nova     |
    +------------+-----------+----------+

Create the host aggregate itself. In this example, the aggregate is called
"exclusive-machines"::

    user@openstack$ nova aggregate-create exclusive-machines
    +----+--------------------+-------------------+-------+----------+
    | 1  | exclusive-machines | -                 |       |          |
    +----+--------------------+-------------------+-------+----------+

Two metadata properties are then set on the host aggregate itself::

    user@openstack$ nova aggregate-set-metadata 1 aggregate_instance_extra_specs:exclusive=true
    Metadata has been successfully updated for aggregate 1.
    +----+--------------------+-------------------+-------+-------------------------------------------------+
    | Id | Name               | Availability Zone | Hosts | Metadata                                        |
    +----+--------------------+-------------------+-------+-------------------------------------------------+
    | 1  | exclusive-machines | -                 |       | 'aggregate_instance_extra_specs:exclusive=true' |
    +----+--------------------+-------------------+-------+-------------------------------------------------+
    user@openstack$ nova aggregate-set-metadata 1 max_instances_per_host=1
    Metadata has been successfully updated for aggregate 1.
    +----+--------------------+-------------------+-------+-----------------------------------------------------------------------------+
    | Id | Name               | Availability Zone | Hosts | Metadata                                                                    |
    +----+--------------------+-------------------+-------+-----------------------------------------------------------------------------+
    | 1  | exclusive-machines | -                 |       | 'aggregate_instance_extra_specs:exclusive=true', 'max_instances_per_host=1' |
    +----+--------------------+-------------------+-------+-----------------------------------------------------------------------------

The first aggregate metadata property is the link between the flavor (still to
be created) and the compute hosts (still to be added to the aggregate). The
second metadata property ensures that nova doesn't ever try to add another
instance to this one in (e.g. if nova is configured to overcommit resources).

Now the hosts must be added to the aggregate. Once they are added to the
host aggregate, they will not be available for other flavors. This will be
important in resource sizing efforts. To add the hosts::

    user@openstack$ nova aggregate-add-host exclusive-machines machine-10
    Host juju-serverstack-machine-10 has been successfully added for aggregate 1 
    +----+--------------------+-------------------+--------------+-----------------------------------------------------------------------------+
    | Id | Name               | Availability Zone | Hosts        | Metadata                                                                    |
    +----+--------------------+-------------------+--------------+-----------------------------------------------------------------------------+
    | 1  | exclusive-machines | -                 | 'machine-10' | 'aggregate_instance_extra_specs:exclusive=true', 'max_instances_per_host=1' |
    +----+--------------------+-------------------+--------------+-----------------------------------------------------------------------------+

Exclusive machine flavors
-------------------------

When planning for exclusive machine flavors, there is still a small amount
of various resources that will be needed for nova compute and lxd itself.
In general, it's a safe bet that this can be quantified in 100MB of RAM,
though specific hosts may need to be configured more closely to their
use cases.

In this example, `machine-10` has 4096MB of total memory, 2 CPUS, and 500GB
of disk space. The flavor that is created will have a quantity of 3996MB of
RAM, 2 CPUS, and 500GB of disk.::

    user@openstack$ nova flavor-create --is-public true e1.medium 100 3996 500 2
    +-----+-----------+-----------+------+-----------+------+-------+-------------+-----------+
    | ID  | Name      | Memory_MB | Disk | Ephemeral | Swap | VCPUs | RXTX_Factor | Is_Public |
    +-----+-----------+-----------+------+-----------+------+-------+-------------+-----------+
    | 100 | e1.medium | 3996      | 500  | 0         |      | 2     | 1.0         | True      |
    +-----+-----------+-----------+------+-----------+------+-------+-------------+-----------+

The `e1.medium` flavor must now have some metadata set to link it with the
`exclusive-machines` host aggregate.::

    user@openstack$ nova flavor-key 100 set exclusive=true


Booting an exclusive instance
-----------------------------

Once the host aggregate and flavor have been created, exclusive machines
can be provisioned by using the flavor `e1.medium`::

    user@openstack$ nova boot --flavor 100 --image $IMAGE exclusive

The `exclusive` instance, once provisioned, will fill the entire host
machine.
