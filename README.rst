OpenStack Agent Liveness
========================

This agent checks the OpenStack Service that the agent using the current hostname is alive. if not, it fails.

return 0 if success (alive)

return 1 if not alive

Usage
-----


    # openstack-agent-liveness --component nova --config-file /etc/nova/nova.conf

    # openstack-agent-liveness --component neutron --config-file /etc/nova/neutron.conf

