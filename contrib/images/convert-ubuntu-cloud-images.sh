#!/bin/bash

VERBOSITY=0
TEMP_D=""
UC_PREP="/usr/share/lxc/hooks/ubuntu-cloud-prep"

error() { echo "$@" 1>&2; }
fail() { [ $# -eq 0 ] || error "$@"; exit 1; }

Usage() {
	cat <<EOF
Usage: ${0##*/} [ options ] input-tar output-tarball

   convert cloud-image-root.tar.gz into lxd compatible format,
   and stuff nocloud seed in on the way.

   options:
      -h|--help         this help
      -v|--verbose
         --metadata     file to include as metadata.yaml
      -u|--userdata U   user-data for seed.
      -S|--auth-key P   pubkey to insert
      -C|--cloud    C   do not seed instance
         --zip      Z   compress with tar option Z (default 'J')
EOF
}

bad_Usage() { Usage 1>&2; [ $# -eq 0 ] || error "$@"; return 1; }
cleanup() {
	[ -z "${TEMP_D}" -o ! -d "${TEMP_D}" ] || rm -Rf "${TEMP_D}"
}

debug() {
	local level=${1}; shift;
	[ "${level}" -gt "${VERBOSITY}" ] && return
	error "${@}"
}

default_mdyaml() {
cat <<EOF
architecture: "$(uname -m)"
creation_date: $(date "+%s")
name: "$1"
properties:
  description: Ubuntu 14.04 LTS Intel 64bit
  os: Ubuntu
  release: [trusty, '14.04']
EOF
}

default_userdata() {
	cat <<EOF
#cloud-config
manage_etc_hosts: localhost
password: ubuntu
chpasswd: { expire: false; }

# pollinate hangs without socket timeout if it can't reach network
random_seed:
   command: null

# growpart and resize_rootfs dont make sense, and should dtrt, but be sure.
growpart:
  mode: off
resize_rootfs: null
EOF
}

main() {
	local short_opts="Chu:S:v"
	local long_opts="auth-key:,cloud,help,metadata:,userdata:,verbose,zip:"
	local getopt_out=""
	local pt=""
	getopt_out=$(getopt --name "${0##*/}" \
		--options "${short_opts}" --long "${long_opts}" -- "$@") &&
		eval set -- "${getopt_out}" ||
		{ bad_Usage; return; }

	local cur="" next="" input="" output="" authkey="" z_opt="J" vflags=""
	local ud=""
	pt=( )

	while [ $# -ne 0 ]; do
		cur="$1"; next="$2";
		case "$cur" in
			-h|--help) Usage ; exit 0;;
			-v|--verbose) VERBOSITY=$((${VERBOSITY}+1))
				vflags="${vflags}v";;
			   --metadata) mdyaml="$next";;
			-u|--userdata)
				ud="$next"; pt[${#pt[@]}]="--userdata=$next"; shift;;
		    -S|--auth-key) pt[${#pt[@]}]="--auth-key=$next"; shift;;
		    -C|--cloud)    pt[${#pt[@]}]="--cloud=$next"; shift;;
		       --zip)	z_opt=$next; shift;;
			--) shift; break;;
		esac
		shift;
	done
	[ -z "$vflags" ] || vflags="-$vflags"

	[ $# -ne 0 ] || { bad_Usage "must provide arguments"; return; }
	[ $# -eq 2 ] ||
		{ bad_Usage "confused by args. got $# expected 2 [$*]"; return; }

	input=$1
	output=$2

	TEMP_D=$(mktemp -d "${TMPDIR:-/tmp}/${0##*/}.XXXXXX") ||
		fail "failed to make tempdir"
	trap cleanup EXIT

	[ "$(id -u)" = "0" ] || { error "you're not root"; return 1; }
	command -v "$UC_PREP" >/dev/null 2>&1 ||
		{ error "$UC_PREP not available"; return 1; }
	[ "$input" = "-" -o -f "$input" ] ||
		{ error "$input: not a file or -"; return 1; }
	[ -n "$output" ] || { error "$output: not a file or -"; return 1; }
	[ -z "$mdyaml" -o -f "$mdyaml" ] ||
		{ error "$mdyaml: not a file"; return 1; }

	if [ -z "$ud" ]; then
		ud="$TEMP_D/user-data"
		default_userdata > "$ud"
		pt[${#pt[@]}]="--userdata=$ud"
	fi

	local extract create ucprep
	mkdir -p "${TEMP_D}/rootfs" || { error "failed to make rootfs"; return 1; }
	extract=(
   		tar -C "${TEMP_D}/rootfs"
	   		--xattrs "--xattrs-include=*"
	   		--anchored "--exclude=dev/*"
	   		--numeric-owner -Sxpf "$input" )

	create=(
		tar -C "${TEMP_D}/"
			--xattrs "--xattrs-include=*"
			-cp${z_opt}f "$output" metadata.yaml rootfs )
	create_pxz=(
		bash -c 'set -o pipefail;
			tar -C "$1" --xattrs "--xattrs-include=*" \
				-cpf - metadata.yaml rootfs |
			pxz -cv - > "$2"' -- "${TEMP_D}" "$output"
	)
	command -v pxz >/dev/null 2>&1 && create=( "${create_pxz[@]}" )

	ucprep=(
		"${UC_PREP}" $vflags "${pt[@]}" "${TEMP_D}/rootfs" )

	if [ -n "$metadata" ]; then
		cp "$metadata" "${TEMP_D}/metadata.yaml" ||
			{ error "failed cp '$metadata' metadata.yaml"; return 1; }
		debug 1 "copied metadata.yaml from '$metadata'"
	else
		local tname=""
   		tname=${input%.gz};
		tname=${tname%.tar};
   		[ "$input" = "-" ] && tname="unknown name"
		default_mdyaml "$tname" > "${TEMP_D}/metadata.yaml" ||
			{ error "failed write metadata.yaml"; return 1; }
		debug 1 "wrote questionable metadata.yaml file"
	fi

	debug 1 "extracting tar to tempdir"
	debug 2 "cmd: ${extract[*]}"
	"${extract[@]}" || { error "failed extraction"; return 1; }

	debug 1 "hacking/fixing for lxd"
	debug 2 "gettys just dont make sense, and upstart restarts"
	( cd "${TEMP_D}/rootfs" &&
		for f in etc/init/tty*.conf; do
			[ -f "$f" ] || continue
			#[ "${f##*/}" = "tty1.conf" ] || continue
			o=${f%.conf}.override
			debug 3 "manual > $o"
			echo "manual" > "$o"
		done
	)

	debug 2 "update-motd runs from mounted-run.conf on mounted tmpfs"
	# this is too late to fix via bootcmd
	nox="
		etc/update-motd.d/90-updates-available
		etc/update-motd.d/91-release-upgrade
		usr/lib/ubuntu-release-upgrader/release-upgrade-motd
		usr/lib/update-notifier/apt-check
		usr/lib/update-notifier/update-motd-updates-available
	"
 	( cd "${TEMP_D}/rootfs" && 
		for f in $nox; do [ -e "$f" ] &&
			debug 3 "chmod -x '$f'" && chmod -x "$f"; done )

	debug 2 "pollinate is heavy, disabling"
	( cd "${TEMP_D}/rootfs"
		f=etc/init/pollinate.conf
		c=${f%.conf}.override
		[ -f "$f" ] && debug 3 "manual > $c" && echo "manual" > "$c"
	)

	debug 2 "mot.d is annoying here (LP: #1426023)"
	# this affects ssh in time. as mot.d is run on ssh login
	( cd "$TEMP_D/rootfs" &&
		sudo sed -i '/^[^#].*pam_motd/s/^/#/' etc/pam.d/sshd )

	debug 2 "disabling irqbalance (LP: #1454273)"
	( cd "$TEMP_D/rootfs" &&
		f=etc/init/irqbalance.conf
		c=${f%.conf}.override
		[ -f "$f" ] && debug 3 "manual > $c" && echo "manual" > "$c" )

	debug 1 "running ucprep: ${ucprep[*]}"
	"${ucprep[@]}" ||
		{ error "failed to run ${ucprep[*]}"; return 1; }

	debug 1 "writing tar to $out: ${create[*]}"
	debug 2 "cmd: ${create[*]}"
	"${create[@]}" || fail "failed writing tar to $out"
	debug 1 "finished [${SECONDS}]"
}

main "$@"
# vi: ts=4 noexpandtab
