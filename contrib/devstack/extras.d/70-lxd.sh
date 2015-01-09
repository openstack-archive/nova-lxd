# lxd.sh - Devstack extras script to install lxd

if [[ $VIRT_DRIVER == "lxd" ]] ; then
	if [[ $1 == "source" ]] ; then
		# Keep track of the current directory
		SCRIPT_DIR=$(cd $(dirname "$0") && pwd)
        TOP_DIR=$SCRIPT_DIR

        echo $SCRIPT_DIR $TOP_DIR

		# Import common functions
        source $TOP_DIR/functions

        # Load local configuration
        source $TOP_DIR/stackrc

        FILES=$TOP_DIR/files

        # Get our defaults
        source $TOP_DIR/lib/nova_plugins/hypervisor-lxd
        source $TOP_DIR/lib/lxd

	elif [[ $2 == "install" ]] ; then
		echo_summary "Configuring LXD"
		
		configure_lxd
		install_lxd
 fi
fi
