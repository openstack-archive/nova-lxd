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

import httplib
import json
import socket

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
        self.unix_socket = CONF.lxd.lxd_socket
        self.conn = UnixHTTPConnection(self.unix_socket)

    def _get(self, path):
        self.conn.request('GET', path)
        return self.conn.getresponse()

    def _put(self, path, data, headers=None):
        self.conn.request('PUT', path, json.dumps(data))
        return self.conn.getresponse()

    def _delete(self, path):
        self.conn.request('DELETE', path)
        return self.conn.getresponse()

    def running(self, name):
        container_running = False
        resp = self._get('/1.0/containers/%s/state' % name)
        if resp.status == 200:
            content = json.loads(resp.read())
            if content['metadata']['state'] == 'RUNNING':
                container_running = True
        return container_running

    def defined(self, name):
        container_exists = False
        resp = self._get('/1.0/containers/%s/state' % name)
        if resp.status == 200:
            content = json.loads(resp.read())
            if content['metadata']['state'] in ['RUNNING', 'UNKNOWN',
                                                'STOPPED', 'FROZEN']:
                container_exists = True
        return container_exists

    def state(self, name):
        resp = self._get('/1.0/containers/%s/state' % name)
        if resp.status == 200:
            operation = json.loads(resp.read())
            return operation['metadata']['state']


    def list(self):
        containers = []
        resp = self._get('/1.0/list')
        if resp:
            data = json.loads(resp.read())
            for i in data['metadata']:
                containers.append(i)
        return containers

    def start(self, name):
        container_start = False
        data = {'action': 'start'}
        resp = self._put('/1.0/containers/%s/state' % name, data)
        if resp.status == 202:
            content = json.loads(resp.read())
            resp = self._get(content['operation'])
            if resp:
                data = json.loads(resp.read())
                if data['metadata']['status'] == 'Running':
                    container_start = True
        return container_start

    def stop(self, name):
        container_stop = False
        data = {'action': 'stop', 'force': True}
        resp = self._put('/1.0/containers/%s/state' % name, data)
        if resp.status == 202:
            container_stop = True
        return container_stop

    def pause(self, name):
        container_pause = False
        data = {'action': 'freeze', 'force': True}
        resp = self._put('/1.0/containers/%s/state' % name, data)
        if resp.status == 202:
            container_pause = True
        return container_pause

    def unpause(self, name):
        container_unpause = False
        data = {'action': 'unfreeze', 'force': True}
        resp = self._put('/1.0/containers/%s/state' % name, data)
        if resp.status == 202:
            container_unpause = True
        return container_unpause

    def reboot(self, name):
        container_reboot = False
        data = {'action': 'restart', 'force': True}
        resp = self._put('/1.0/containers/%s/state' % name, data)
        if resp.status == 202:
            container_reboot = True
        return container_reboot

    def destroy(self, name):
        container_delete = False
        resp = self._delete('/1.0/containers/%s' % name)
        if resp.statu == 202:
            container_delete = True
        return container_delete
