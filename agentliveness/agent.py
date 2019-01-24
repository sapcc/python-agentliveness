# Copyright 2018 SAP SE
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.
from keystoneauth1.exceptions import ClientException
from keystoneauth1.identity import v3
from keystoneauth1 import session
from neutronclient.v2_0 import client as neutron_client
from novaclient import client as nova_client

class Liveness(object):
    def __init__(self, CONF):
        self.CONF = CONF

    def check(self):
        if self.CONF.component == 'neutron':
            return self._check_neutron()
        if self.CONF.component == 'nova':
            return self._check_nova()

    def _check_neutron(self):
        neutron = neutron_client.Client(session=self._get_session())
        try:
            for agent in neutron.list_agents(host=self.CONF.host):
                if agent.get('alive', False):
                    return 0
                else:
                    return 1
        except ClientException:
            # keystone/neutron Down, return 0
            return 0

    def _check_nova(self):
        nova = nova_client.Client(version='2.1', session=self._get_session())
        try:
            for agent in nova.services.list(host=self.CONF.host):
                if agent.state == 'up':
                    return 0
                else:
                    return 1
        except ClientException:
            # keystone/nova Down, return 0
            return 0

    def _get_session(self):
        auth_url = self.CONF.keystone_authtoken.auth_url
        user = self.CONF.keystone_authtoken.username
        pw = self.CONF.keystone_authtoken.password
        project_name = self.CONF.keystone_authtoken.project_name or 'service'
        user_domain_name = (self.CONF.keystone_authtoken.user_domain_name or
                            'default')
        project_domain_name = (self.CONF.keystone_authtoken.project_domain_name
                               or 'default')
        auth = v3.Password(auth_url=auth_url,
                           username=user,
                           password=pw,
                           project_name=project_name,
                           user_domain_name=user_domain_name,
                           project_domain_name=project_domain_name)
        return session.Session(auth=auth)
