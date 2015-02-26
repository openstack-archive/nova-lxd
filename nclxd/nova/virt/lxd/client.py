# Copyright (c) 2015 Canonical Ltd
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import json
import socket

from eventlet.green import httplib

from oslo.config import cfg

CONF = cfg.CONF

class UnixHTTPConnection(httplib.HTTPConnection):

    def __init__(self, path, host='localhost', port=None, strict=None,
                timeout=None):
        httplib.HTTPConnection.__init__(self, host, port=port, strict=strict,
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
        self.conn = UnixHTTPConnection(self.unix_socket)
        self.conn.request(*args, **kwargs)
        resp = self.conn.getresponse()

        data = json.loads(resp.read())

        return resp.status, data


    def running(self, name):
        container_running = False
        (status, data) = self._make_request('GET',
                                  '/1.0/containers/%s/state' % name)
        if status == 200:
            if data['metadata']['state'] == 'RUNNING':
                container_running = True
        return container_running

    def defined(self, name):
        container_exists = False
        (status, data) = self._make_request('GET',
                                  '/1.0/containers/%s/state' % name)
        if status == 200:
            if data['metadata']['state'] in ['RUNNING', 'UNKNOWN',
                                                'STOPPED', 'FROZEN']:
                container_exists = True
        return container_exists

    def state(self, name):
        (status, data) = self._make_request('GET', '/1.0/containers/%s/state' % name)
        if status == 200:
            return data['metadata']['state']

    def list(self):
        (status, data) = self._make_request('GET', '/1.0/list')
        if status != 200:
            return []
        return [container.split('/1.0/list')[-1] for container in data['metadata']]

    def start(self, name):
        container_start = False
        action = {'action': 'start'}
        (status, data) = self._make_request('PUT', '/1.0/containers/%s/state' % name,
                                  json.dumps(action))
        if status == 202:
            container_start = True
        return container_start

    def stop(self, name):
        container_stop = False
        action = {'action': 'stop', 'force': True}
        (status, data) = self._make_request('PUT', '/1.0/containers/%s/state' % name,
                                  json.dumps(action))
        if status == 202:
            container_stop = True
        return container_stop

    def pause(self, name):
        container_pause = False
        action = {'action': 'freeze', 'force': True}
        (status, data) = self._make_request('PUT', '/1.0/containers/%s/state' % name,
                                  json.dumps(action))
        if status == 202:
            container_pause = True
        return container_pause

    def unpause(self, name):
        container_unpause = False
        action = {'action': 'unfreeze', 'force': True}
        (status, data) = self._make_request('PUT', '/1.0/containers/%s/state' % name,
                                  json.dumps(action))
        if status == 202:
            container_unpause = True
        return container_unpause

    def reboot(self, name):
        container_reboot = False
        action = {'action': 'restart', 'force': True}
        (status, data) = self._make_request('PUT', '/1.0/containers/%s/state' % name,
                                  json.dumps(action))
        if status == 202:
            container_reboot = True
        return container_reboot

    def destroy(self, name):
        container_delete = False
        (status, data) = self._make_request('DELETE', '/1.0/containers/%s' % name)
        if status == 202:
            container_delete = True
        return container_delete

    def list_images(self):
        (status, data) = self._make_request('GET', '/1.0/images')
        return [image.split('/1.0/images')[-1] for image in data['metadata']]

    def list_aliases(self):
        status, data = self._make_request('/1.0/images/aliases')
        return [alias.split('/1.0/aliases')[-1] for alias in data['metadata']]

    def create_alias(self, alias, fingerprint):
        container_alias = False
        action = {'target': fingerprint,
                  'name': alias}
        (status, data) = self._make_request('POST','/1.0/images/aliases', json.dumps(action))
        if status == 200:
            container_alias = True
        return container_alias

