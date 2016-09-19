#!/bin/bash

# Construct a regex t ouse when limiting scope of tempest
# to avoid features unsupported by nova-lxd

# Note that several tests are disabled by the use of tempest
# feature toggels in devstack for an LXD config
# so this regex is not entiriely representative of 
# what's excluded

# Wen adding entries to the ignored_tests, add a comment explaining
# why since this list should not grow

# Temporarily skip the image tests since they give false positivies
# for nova-lxd

ignored_tests="|^tempest.api.compute.images"

# Regressions
ignored_tests="$ignored_tests|.*AttachInterfacesTestJSON.test_create_list_show_delete_interfaces"

# backups are not supported
ignored_tests="$ignored_tests|.*ServerActionsTestJSON.test_create_backup"

# failed verfication tests
ignored_tests="$ignored_tests|.*ServersWithSpecificFlavorTestJSON.test_verify_created_server_ephemeral_disk"
ignored_tests="$ignored_tests|.*AttachVolumeShelveTestJSON.test_attach_detach_volume"
ignored_tests="$ignored_tests|.*AttachVolumeTestJSON.test_attach_detach_volume"

regex="(?!.*\\[.*\\bslow\\b.*\\]$ignored_tests)(^tempest\\.api.\\compute)"; 

ostestr --serial --regex $regex run

