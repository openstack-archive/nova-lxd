def get_container_cgroups_path():
    with open('/proc/mounts') as f:
        for line in f.readlines():
            fields = line.split(' ')
            if fields[2] == 'cgroup' and 'devices' in fields[3].split(','):
                return fields[1]
