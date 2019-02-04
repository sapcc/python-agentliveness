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
try:
    from cinderclient.v3 import client as cinder_client
except ImportError:
    from cinderclient.v2 import client as cinder_client
from keystoneauth1 import session
from keystoneauth1.exceptions import ClientException
from keystoneauth1.identity import v3
from neutronclient.v2_0 import client as neutron_client
from novaclient import client as nova_client
from oslo_log import log as logging

LOG = logging.getLogger(__name__)


class Liveness(object):
    def __init__(self, CONF):
        self.CONF = CONF

    def check(self):
        if self.CONF.component == 'neutron':
            if self.CONF.dhcp_ready:
                return self._check_neutron_dhcp_agent()
            return self._check_neutron()
        if self.CONF.component == 'nova':
            return self._check_nova()
        if self.CONF.component == 'cinder':
            return self._check_cinder()

        LOG.error("Error: No component found / determined")
        return 1

    def _check_neutron(self):
        neutron = neutron_client.Client(session=self._get_session(), endpoint_type='internal')
        try:
            params = {'host': self.CONF.host}
            if self.CONF.binary:
                params.update({'binary': self.CONF.binary})
            for agent in neutron.list_agents(**params).get('agents', []):
                if agent.get('alive', False):
                    return 0
                else:
                    return 1

            LOG.error("Warning: Agent hostname %s not registered" % self.CONF.host)
        except ClientException as e:
            # keystone/neutron Down, return 0
            LOG.error("Warning: Keystone or Neutron down, cannot determine liveness: ", e)

        return 0

    def _check_neutron_dhcp_agent(self):
        neutron = neutron_client.Client(session=self._get_session(), endpoint_type='internal')
        try:
            params = {'host': self.CONF.host, 'agent_type': 'DHCP agent'}
            if self.CONF.binary:
                params.update({'binary': self.CONF.binary})
            for agent in neutron.list_agents(**params).get('agents', []):
                if agent.get('alive', False):
                    dhcp_subnets = neutron.list_subnets(enable_dhcp=True, fields='network_id',
                                               sort_key='network_id', sort_dir='asc')
                    # if synced subnets is larger/equal dhcp-enabled subnets
                    if len(dhcp_subnets['subnets']) <= agent['configurations'].get('subnets', 0):
                        return 0

                    LOG.warning("Warning: Not all Networks synced (%d < %d)" %
                              (agent['configurations'].get('subnets', 0), len(dhcp_subnets['subnets'])))
                    return 1
                else:
                    LOG.error("DHCP Agent down")
                    return 1

            LOG.error("Warning: Agent hostname %s not registered" % self.CONF.host)
        except ClientException as e:
            # keystone/neutron Down, return 0
            LOG.error("Warning: Keystone or Neutron down, cannot determine liveness: ", e)

        return 0

    def _check_nova(self):
        nova = nova_client.Client(version='2.1', session=self._get_session(), endpoint_type='internal')
        try:
            for agent in nova.services.list(host=self.CONF.host):
                if agent.state == 'up':
                    return 0
                else:
                    return 1

            LOG.error("Warning: Agent hostname not %s registered" % self.CONF.host)
        except ClientException as e:
            # keystone/nova Down, return 0
            LOG.error("Warning: Keystone or Nova down, cannot determine liveness: ", e)

        return 0

    def _check_cinder(self):
        cinder = cinder_client.Client(session=self._get_session())
        try:
            for agent in cinder.services.list(host=self.CONF.host):
                if agent.state == 'up':
                    return 0
                else:
                    return 1

            LOG.error("Warning: Agent hostname not %s registered" % self.CONF.host)
        except ClientException as e:
            # keystone/nova Down, return 0
            LOG.error("Warning: Keystone or Cinder down, cannot determine liveness: ", e)

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