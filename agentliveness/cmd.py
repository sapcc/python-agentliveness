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
import socket
import sys

from keystoneauth1 import loading as ks_loading
from oslo_config import cfg

logger = logging.getLogger(__name__)


host_opts = [
    cfg.StrOpt("host",
               default=socket.gethostname(),
               sample_default='<current_hostname>',
               help="Hostname"),
    cfg.ListOpt('enabled_share_backends',
                default=[],
                help='For manila only.'
                     'A list of share backend names to use. These backend '
                     'names should be backed by a unique [CONFIG] group '
                     'with its options.'),
]

auth_opts = [
    cfg.StrOpt("username",
               default=None,
               help="This should be the username of a user WITHOUT "
                    "administrative privileges."),
    cfg.StrOpt("tenant_name",
               default=None,
               help="The non-administrative user's tenant name."),
    cfg.StrOpt("password",
               default=None,
               help="The non-administrative user's password."),
    cfg.StrOpt("auth_url",
               default="",
               help="URL for where to find the OpenStack Identity public "
                    "API endpoint."),
    cfg.StrOpt("admin_username",
               default=None,
               help="This should be the username of a user WITH "
                    "administrative privileges."),
    cfg.StrOpt("admin_tenant_name",
               default=None,
               help="The administrative user's tenant name."),
    cfg.StrOpt("admin_password",
               default=None,
               help="The administrative user's password."),
    cfg.StrOpt("admin_auth_url",
               default=None,
               help="URL for where to find the OpenStack Identity admin "
                    "API endpoint."),
    cfg.BoolOpt("insecure",
                default=False,
                help="Disable SSL certificate verification."),
    cfg.StrOpt("project_name",
               default=None,
               help="Project Name."),
    cfg.StrOpt("user_domain_name",
               default=None,
               help="User Domain Name."),
    cfg.StrOpt("project_domain_name",
               default=None,
               help="Project Domain Name."),
]


def main():
    cli_opts = [
        cfg.StrOpt('component',
                   short='c',
                   choices=['neutron', 'nova', 'cinder', 'manila'],
                   help='Openstack Service to check'),
        cfg.StrOpt('binary',
                    short='b',
                    default=None,
                    help='For neutron agent, filter for this binary'),
        cfg.BoolOpt('dhcp_ready',
                    short='r',
                    default=False,
                    help='check that dhcp-agent has all networks synced'),
    ]

    conf = cfg.CONF
    conf.register_cli_opts(cli_opts)
    logging.basicConfig(level=logging.WARNING)
    ks_loading.register_auth_conf_options(conf, 'keystone_authtoken')
    ks_loading.register_auth_conf_options(conf, 'nova')
    ks_loading.register_session_conf_options(conf, 'nova')
    conf.register_opts(auth_opts, 'keystone_authtoken')
    conf.register_opts(host_opts)
    conf(sys.argv[1:])

    if conf.component is None:
        # Try guessing service type
        tokens = conf.host.split('-')
        if len(tokens) > 1:
            try:
                conf.component = next(x for x in ['neutron', 'nova', 'cinder', 'manila'] if x == tokens[0])
            except StopIteration:
                logging.critical("Error, no component mode defined, use --component")
                sys.exit(1)

    from agentliveness.agent import Liveness
    return Liveness(conf).check()


if __name__ == "__main__":
    sys.exit(main())
