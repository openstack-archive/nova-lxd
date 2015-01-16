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
import requests

class Client(object):
    def __init__(self, host, cert, key):
        self.host = host
        self.cert = cert
        self.key = key

    def _url(self, path):
        return 'https://{0}{1}'.format(self.host, path)

    def _get(self, path):
        return requests.get(self._url(path),
                            cert=(self.cert, self.key), verify=False)

    def _put(self, path, data):
        return requests.put(self._url(path), data=json.dumps(data),
                            cert=(self.cert, self.key), verify=False)

    def _delete(self, path):
        return requests.delete(self._url(path), 
                               cert=(self.cert, self.key), verify=False)

    def defined(self, name):
        container_exists = False
        response = self._get('/1.0/containers/%s/state' % name)
        if response:
            container_exists = True
        return container_exists

    def running(self, name):
        container_running = False
        if self.defined(name):
            response = self._get('/1.0/containers/%s/state' % name)
            if response:
                content = json.loads(response.text)
                if content['metadata']['state'] != 'STOPPED':
                    container_running = True
        return container_running

    def state(self, name):
        if self.defined(name):
            response = elf._get('/1.0/containers/%s/state' % name)
            if response:
                content = json.loads(response.text)
                return content['metadata']['state']

    def start(self, name):
        container_start = False
        if self.defined(name):
            params = {'action':'start'}
            response = self._put('/1.0/containers/%s/state' % name, params)
            if response.status_code == 200:
                container_start = True
        return container_start

    def stop(self, name):
        container_stop = False
        if self.defined(name):
            params = {'action':'start'}
            response = self._put('/1.0/containers/%s/state' % name, params)
            if response.status_code == 200:
                container_stop = True
        return container_stop

    def pause(self, name):
        container_pause = False
        if self.defined(name):
            params = {'action': 'freeze'}
            response = self._put('/1.0/containers/%s/state' % name, params)
            if response.status_code == 200:
                container_pause = True
        return container_pause

    def unpause(self, name):
        container_unpause = False
        if self.defined(name):
            params = {'action': 'unfreeze'}
            response = self._put('/1.0/containers/%s/state' % name, params)
            if response.status_code == 200:
                container_unpause = True
        return container_unpause

    def reboot(self, name):
        container_reboot = False
        if self.defined(name):
            params = {'action': 'restart'}
            response = self._put('/1.0/containers/%s/state' % name, params)
            if response.status_code == 200:
                container_reboot = True
        return container_reboot

    def destroy(self, name):
        container_delete = False
        if self.defined(name):
            response = self._delete('/1.0/containers/%s' % name)
            if response.status_code == 200:
                container_delete = True
        return container_delete

    def list(self):
        containers = []
        response = self._get('/1.0/list')
        if response:
            content = json.loads(response.text)
            for i in content['metadata']:
                containers.append(i)
        return containers
