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
import logging
import os

try:
    from cinderclient.v3 import client as cinder_client
except ImportError:
    from cinderclient.v2 import client as cinder_client
from ironicclient import client as ironic_client
from ironicclient.common.apiclient import exceptions as ironic_exceptions
from keystoneauth1 import session as ka_session
from keystoneauth1.exceptions import ClientException
from keystoneauth1.identity import v3
from manilaclient.v2 import client as manila_client
from neutronclient.common.exceptions import ServiceUnavailable
from neutronclient.v2_0 import client as neutron_client
from novaclient import client as nova_client


logger = logging.getLogger(__name__)


class Liveness:
    def __init__(self, conf, consistent_storage):
        self.CONF = conf
        self._persistent_storage = consistent_storage

    def check(self):
        if self.CONF.component == 'neutron':
            if self.CONF.dhcp_ready:
                return self._check_neutron_dhcp_agent()
            return self._check_neutron()
        if self.CONF.component == 'nova':
            return self._check_nova()
        if self.CONF.component == 'cinder':
            return self._check_cinder()
        if self.CONF.component == 'manila':
            return self._check_manila()
        if self.CONF.component == 'ironic':
            return self._check_ironic()

        logger.error("No component found / determined")
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
                    logger.error("Agent %s is down, commencing suicide", agent['id'])
                    return 1

            logger.warning("Agent hostname %s not registered", self.CONF.host)
        except (ClientException, ServiceUnavailable) as e:
            # keystone/neutron Down, return 0
            logger.warning("Keystone or Neutron down, cannot determine liveness: %s", e)

        return 0

    def _check_neutron_dhcp_agent(self):
        neutron = neutron_client.Client(session=self._get_session(), endpoint_type='internal')
        try:
            params = {'host': self.CONF.host, 'agent_type': 'DHCP agent'}
            if self.CONF.binary:
                params.update({'binary': self.CONF.binary})
            for agent in neutron.list_agents(**params).get('agents', []):
                if agent.get('alive', False):
                    enabled_networks = [
                        x for x in
                        neutron.list_networks_on_dhcp_agent(agent['id']).get('networks')
                        if x.get('admin_state_up', False)
                    ]
                    # if synced networks is larger/equal dhcp-enabled subnets
                    if len(enabled_networks) <= agent['configurations'].get('networks', 0):
                        return 0

                    """ We have more networks scheduled than synced, check if the currently
                        missing one are non-externals """

                    netns_path = '/run/netns'
                    netns = [self.remove_prefix(f, 'qdhcp-') for f in os.listdir(netns_path)
                             if os.path.isfile(netns_path + '/' + f)]
                    for net in enabled_networks:
                        if net.get('id') not in netns and not net.get('router:external'):
                            logger.warning(" %d/%d synced, internal network '%s' not synced",
                                           len(netns), len(enabled_networks), net.get('id'))
                            return 1

                    # All non-external networks synced, return OK.
                    return 0
                else:
                    logger.error("DHCP Agent down")
                    return 1

            logger.warning("Agent hostname %s not registered", self.CONF.host)
        except (ClientException, ServiceUnavailable) as e:
            # keystone/neutron Down, return 0
            logger.warning("Keystone or Neutron down, cannot determine liveness: %s", e)
        except OSError as e:
            # /run/netns not existing yet
            logger.warning("Namespace not created yet: %s", e)
            return 1
        return 0

    def _check_nova(self):
        nova = nova_client.Client(version='2.1', session=self._get_session(), endpoint_type='internal')
        try:
            for service in nova.services.list(host=self.CONF.host):
                if service.state == 'up':
                    return 0
                else:
                    logger.error("Agent %s is down, commencing suicide", service.id)
                    return 1

            logger.warning("Agent hostname not %s registered", self.CONF.host)
        except ClientException as e:
            # keystone/nova Down, return 0
            logger.warning("Keystone or Nova down, cannot determine liveness: %s", e)

        return 0

    def _check_cinder(self):
        cinder = cinder_client.Client(session=self._get_session())
        try:
            for service in cinder.services.list(host=self.CONF.host):
                if service.state == 'up':
                    return 0
                else:
                    if service.status == 'enabled':
                        logger.error("Agent %s is down, commencing suicide",
                                     service.host)
                        return 1
                    else:
                        logger.warning("Cinder service is manually disabled"
                                       " for host %s", service.host)
                        return 0

            logger.warning("Agent hostname not %s registered", self.CONF.host)
        except ClientException as e:
            # keystone/nova Down, return 0
            logger.warning("Keystone or Cinder down, cannot determine liveness: %s", e)

        return 0

    def _check_manila(self):
        manila = manila_client.Client(session=self._get_session(), endpoint_type='internal')
        try:
            if self.CONF.enabled_share_backends:
                hosts = [f"{self.CONF.host}@{backend}" for backend in self.CONF.enabled_share_backends]
            else:
                hosts = [self.CONF.host]

            for host in hosts:
                agent_services = manila.services.list({'host': host})
                if len(agent_services) == 0:
                    logger.error("Agent hostname %s not registered", host)
                    return 1
                for service in agent_services:
                    # state is binary 'up' or 'down'
                    # https://github.com/openstack/manila/blob/b7d2fe164d73078c412a7d4240aa06f2a8b6de72/manila/api/v2/services.py#L50 # noqa: E501
                    if service.state == 'down':
                        # even one backend down out of multiple backends qualifies for reporting 'not live'
                        logger.error("Agent %s is down, commencing suicide", service.host)
                        return 1

        except ClientException as e:
            # keystone/manila Down, return 0
            logger.warning("Keystone or Manila down, cannot determine liveness: %s", e)

        return 0

    def _check_ironic(self):
        host = self.CONF.ironic_conductor_host
        if host is None:
            logger.warning("please provide a ironic conductor host")
            return 0

        ironic = ironic_client.get_client(session=self._get_session(), endpoint_type='internal', api_version='1',
                                          os_ironic_api_version='1.58')
        try:
            try:
                conductor = ironic.conductor.get(self.CONF.ironic_conductor_host)
                if not conductor.alive:
                    logger.error("Conductor %s is not alive, commencing suicide", self.CONF.ironic_conductor_host)
                    return 1
            except ironic_exceptions.NotFound:
                logger.error("Conductor %s not found, commencing suicide", self.CONF.ironic_conductor_host)
                return 1

            drivers = ironic.driver.list()
            for driver in drivers:
                if self.CONF.ironic_conductor_host in driver.hosts:
                    break
            else:
                logger.error("Conductor %s is not listed for any driver, commencing suicide",
                             self.CONF.ironic_conductor_host)
                return 1

        except ClientException as e:
            # keystone/ironic Down, return 0
            logger.warning("Keystone or Ironic down, cannot determine liveness: %s", e)

        return 0

    def _get_session_with_token_cache(self):
        """Read the token from file and see if it still works

        Returns `None` if the token didn't exist or expired.
        """
        try:
            auth_ref = self._persistent_storage['auth_ref']
        except KeyError:
            return None

        if auth_ref is None:
            return None

        auth = v3.Token(
            self.CONF.keystone_authtoken.auth_url,
            auth_ref.auth_token)
        # we overwrite the auth_ref with our cached one to include the service
        # endpoints without having to make a request against keystone
        auth.auth_ref = auth_ref

        session = ka_session.Session(auth=auth)

        # this checks if the token expires soon and renews the token
        # automatically if possible
        try:
            session.auth.get_access(session)
        except Exception as e:
            logger.error(e)
            return None

        return session

    def _get_session(self):
        if self._persistent_storage is not None:
            session = self._get_session_with_token_cache()
            if session is not None:
                return session

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
        session = ka_session.Session(auth=auth)
        if self._persistent_storage is not None:
            self._persistent_storage['auth_ref'] = session.auth.get_access(session)
        return session

    @staticmethod
    def remove_prefix(text, prefix):
        if text.startswith(prefix):
            return text[len(prefix):]
        return text
