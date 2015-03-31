#!/usr/bin/python

import json
import optparse
import os
import subprocess
import tempfile
import time

def parse_argv():
	optparser = optparse.OptionParser()
	optparser.add_option('-i', '--image',
						 help='Path to image', dest='image', metavar='PATH')
	(opts, args) = optparser.parse_args()

	if not os.path.exists(opts.image):
		optparser.error('Unable to open file')

	return (opts, args)

def create_tarball():
	workdir = tempfile.mkdtemp()
	rootfs_dir = os.path.join(workdir, 'rootfs')
	os.mkdir(rootfs_dir)
	image = opts.image
	r = subprocess.call(['tar', '--anchored', '--numeric-owner', 
						 '--exclude=dev/*', '-zxf', image,
                         '-C', rootfs_dir])

	epoch = time.time()
	metadata = {
		'architecutre': 'x86_64',
		'creation_date': int(epoch)
	}
	metadata_yaml = json.dumps(metadata, sort_keys=True,
							   indent=4, separators=(',', ': '),
							   ensure_ascii=False).encode('utf-8') + b"\n"
	metadata_file = os.path.join(workdir, 'metadata.yaml')
	with open(metadata_file, 'w') as fp:
		fp.write(metadata_yaml)
	source_tarball = image.split('.')
	dest_tarball = "%s-lxd.tar.gz"  % source_tarball[0]
	r = subprocess.call(['tar', '-C', workdir, '-zcvf',
						 dest_tarball, 'metadata.yaml', 'rootfs'])

if __name__ == '__main__':
	(opts, args) = parse_argv()

	create_tarball()
