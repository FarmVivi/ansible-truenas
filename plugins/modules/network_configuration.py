#!/usr/bin/python
# -*- coding: utf-8 -*-
__metaclass__ = type

DOCUMENTATION = r'''
---
module: network_configuration
short_description: Manage TrueNAS global network configuration
description:
  - Idempotently manages C(network.configuration.update) settings.
  - This module manages global routing, DNS and naming settings; use a
    dedicated interface module for interface addresses.
options:
  hostname:
    description: System hostname.
    type: str
  domain:
    description: System domain name.
    type: str
  ipv4gateway:
    description: Static IPv4 default gateway, or an empty string to clear it.
    type: str
  ipv6gateway:
    description: Static IPv6 default gateway, or an empty string to clear it.
    type: str
  nameservers:
    description:
      - Ordered list of zero to three DNS server addresses.
      - Missing slots are explicitly cleared.
    type: list
    elements: str
  httpproxy:
    description: HTTP proxy used for network operations, or empty to disable.
    type: str
  hosts:
    description: Static host entries managed by TrueNAS.
    type: list
    elements: str
  domains:
    description: Additional DNS search domains.
    type: list
    elements: str
  service_announcement:
    description: Service discovery protocols to advertise.
    type: dict
    suboptions:
      netbios:
        type: bool
      mdns:
        type: bool
      wsd:
        type: bool
  hostname_b:
    description: Hostname of the second HA controller.
    type: str
  hostname_virtual:
    description: Virtual hostname for an HA system.
    type: str
notes:
  - Supports check mode.
version_added: 2.1.0
'''

EXAMPLES = r'''
- name: Configure global networking
  arensb.truenas.network_configuration:
    hostname: library-skaro-01
    domain: skaro.home
    ipv4gateway: 10.2.2.1
    nameservers:
      - 10.2.2.2
    service_announcement:
      netbios: false
      mdns: true
      wsd: true
'''

RETURN = r'''
changed_fields:
  description: Settings that were or would be changed.
  returned: always
  type: list
  elements: str
'''

from ansible.module_utils.basic import AnsibleModule
from ..module_utils.middleware import MiddleWare as MW


OPTIONS = (
    'hostname',
    'domain',
    'ipv4gateway',
    'ipv6gateway',
    'httpproxy',
    'hosts',
    'domains',
    'service_announcement',
    'hostname_b',
    'hostname_virtual',
)


def main():
    module = AnsibleModule(
        argument_spec=dict(
            hostname=dict(type='str'),
            domain=dict(type='str'),
            ipv4gateway=dict(type='str'),
            ipv6gateway=dict(type='str'),
            nameservers=dict(type='list', elements='str'),
            httpproxy=dict(type='str'),
            hosts=dict(type='list', elements='str'),
            domains=dict(type='list', elements='str'),
            service_announcement=dict(
                type='dict',
                options=dict(
                    netbios=dict(type='bool'),
                    mdns=dict(type='bool'),
                    wsd=dict(type='bool'),
                ),
            ),
            hostname_b=dict(type='str'),
            hostname_virtual=dict(type='str'),
        ),
        supports_check_mode=True,
    )

    mw = MW.client()
    try:
        current = mw.call('network.configuration.config')
    except Exception as e:
        module.fail_json(msg=f'Error looking up network configuration: {e}')

    update = {}
    for option in OPTIONS:
        desired = module.params[option]
        if desired is not None and current.get(option) != desired:
            update[option] = desired

    nameservers = module.params['nameservers']
    if nameservers is not None:
        if len(nameservers) > 3:
            module.fail_json(msg='nameservers accepts at most three addresses.')
        for index in range(3):
            field = f'nameserver{index + 1}'
            desired = nameservers[index] if index < len(nameservers) else ''
            if current.get(field, '') != desired:
                update[field] = desired

    result = {
        'changed': bool(update),
        'changed_fields': sorted(update.keys()),
    }
    if not update or module.check_mode:
        module.exit_json(**result)

    try:
        mw.call('network.configuration.update', update)
    except Exception as e:
        module.fail_json(
            msg=(f'Error updating network configuration fields '
                 f'{result["changed_fields"]}: {e}'))

    module.exit_json(**result)


if __name__ == '__main__':
    main()
