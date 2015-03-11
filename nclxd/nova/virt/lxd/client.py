import httplib
import json
import socket


class UnixHTTPConnection(httplib.HTTPConnection):
    def __init__(self, path, host='localhost', port=None, strict=None,
                 timeout=None):
        httplib.HTTPConnection.__init__(self, host, port=port,
                                        strict=strict,
                                        timeout=timeout)
        self.path = path

    def connect(self):
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(self.path)
        self.sock = sock

class Client(object):
    def __init__(self):
	self.unix_socket = '/var/lib/lxd/unix.socket'

    def _make_request(self, *args, **kwargs):
        conn = UnixHTTPConnection(self.unix_socket)
        conn.request(*args, **kwargs)
        response = conn.getresponse()
        data = json.loads(response.read())
        return response.status, data

    # host ping
    def ping(self):
        (status, data) = self._make_request('GET', '/1.0')
        return { 'status_code': data.get('status'),
                 'status': data.get('status_code')
               }

    # containers
    def container_list(self):
        (status, data) = self._make_request('GET', '/1.0/containers')
        return [container.split('/1.0/containers/')[-1]
                for container in data['metadata']]

    def container_info(self, container):
        (status, data) = self._make_request('GET', '/1.0/containers/%s'
                                            % container)
        if data.get('type') == 'error':
            return  {
                     'status_code': data.get('error_code'),
                     'status': data.get('error')
                    }

        container = data.get('metadata')
        container_status = container.get('status')
        return {'status_code': str(data.get('status_code')),
                'status': str(data.get('status')),
                'name': str(container.get('name')),
                'config': str(container.get('config', 'None')),
                'profiles': str(container.get('profile', 'None')),
                'userdata': str(container.get('userdata', 'None')),
                'container_status': str(container_status.get('status', "None"))}


    def container_defined(self, name):
        (status, data) = self._make_request('GET', '/1.0/containers/%s' % name)
        container_defined = False
        if data.get('type') != 'error':
            container_defined = True
        return container_defined

    def container_running(self, name):
        container_running = False
        (status, data) = self._make_request('GET', '/1.0/containers/%s' % name)
        metadata = data.get('metadata')
        if metadata.get('status') == 'RUNNING':
            container_running = True
        return container_running

    def container_init(self, config):
        (status, data) = self._make_request('POST', '/1.0/containers',
                                            json.dumps(config))
        print data
        return (status, data)

    def container_start(self, name):
        action = {'action': 'start', 'force': True}
        (status, data) = self._make_request('PUT', '/1.0/containers/%s/state'
                                            % name)
        print data
        return (status, data)

    def container_delete(self, name):
        (status, data) = self._make_request('DELETE', '/1.0/containers/%s'
                                            % name)
        return (status, data)


    # profiles
    def profile_list(self):
        (status, data) = self._make_request('GET', '/1.0/profiles')
        return [profile.split('/1.0/profiles/')[-1]
                    for profile in data['metadata']]

    def profile_create(self, config):
        (status, data) = self._make_request('POST', '/1.0/profiles',
                                                json.dumps(config))
        return (status, data)

    def profile_update(self, name, config):
        (status, data) = self._make_request('PUT', '/1.0/profiles/%s' % name,
                                            json.dumps(config))
        reutrn (status, data)

    def profile_show(self, name):
        (status, data) = self._make_request('GET', '/1.0/profiles/%s' % name)

        container_profile  = data.get('metadata')

        return {'status': data.get('status'),
                'status_code': data.get('status_code'),
                'profile': str(container_profile.get('config', 'None')),
                'devices': str(container_profile.get('devices', 'None'))}

    # images
    def image_list(self):
        (status, data) = self._make_request('GET', '/1.0/images')
        return [image.split('/1.0/images/')[-1] for image in data['metadata']]

    def image_upload(self, path, filename):
        (status, data) = self._make_request('POST', '/1.0/images',
                                            open(path, 'rb'))
        return (status, data)

    def image_delete(self, name):
        (status, data) = self._make_request('DELETE', '/1.0/images/%s' % name)
        return (status, data)

    def image_export(self, name):
        raise NotImplemented()

    # aliases
    def alias_list(self):
        (status, data) = self._make_request('GET', '/1.0/images/aliases')
        return [alias.split('/1.0/aliases/')[-1] for alias in data['metadata']]

    def alias_create(self, name, target):
        payload = {'target': target, 'name': name}
        (status, data) = self._make_request('POST', '/1.0/images/aliases', json.dumps(payload))
        print data
        return (status, data)

    def alias_delete(self, name):
        (status, data) = self._make_request('DELETE', '/1.0/images/aliases/%s' % name)
        return (status, data)
