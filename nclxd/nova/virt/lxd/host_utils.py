import os

def get_fs_info(path):
    """get free/used/total space info for a filesystem

    :param path: Any dirent on the filesystem
    :returns: A dict containing

              :free: How much space is free (in bytes)
              :used: How much space is used (in bytes)
              :total: How big the filesytem is (in bytes)
    """
    hddinfo = os.statvfs(path)
    total = hddinfo.f_frsize * hddinfo.f_blocks
    free = hddinfo.f_frsize * hddinfo.f_bavail
    used = hddinfo.f_frsize * (hddinfo.f_blocks - hddinfo.f_bfree)
    return {'total': total,
            'free': free,
            'used': used}

def get_memory_mb_usage():
    """Get the used memory size(MB) of the host.

    "returns: the total usage of memory(MB)
    """

    with open('/proc/meminfo') as fp:
        m = fp.read().split()
        idx1 = m.index('MemTotal:')
        idx2 = m.index('MemFree:')
        idx3 = m.index('Buffers:')
        idx4 = m.index('Cached:')
    
        total = int(m[idx1 + 1])
        avail = int(m[idx2 + 1]) + int(m[idx3 + 1]) + int(m[idx4 + 1])

    return {
        'total': total * 1024,
        'used': (total - avail) * 1024
    }
