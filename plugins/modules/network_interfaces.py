#!/usr/bin/python
# -*- coding: utf-8 -*-
__metaclass__ = type

DOCUMENTATION = r'''
---
module: network_interfaces
short_description: Manage existing TrueNAS network interfaces transactionally
description:
  - Idempotently manages addresses and common settings on existing interfaces.
  - All interface changes are staged before a single commit, preventing a
    partially-applied multi-interface configuration.
  - The commit uses the TrueNAS rollback timer and is immediately confirmed
    after middleware accepts the complete configuration.
options:
  interfaces:
    description: Existing interfaces and their desired managed settings.
    type: list
    elements: dict
    required: true
    suboptions:
      name:
        description: TrueNAS interface name, for example C(ens18).
        type: str
        required: true
      description:
        description: Human-readable interface description.
        type: str
      ipv4_dhcp:
        description: Obtain IPv4 configuration through DHCP.
        type: bool
      ipv6_auto:
        description: Obtain IPv6 configuration automatically.
        type: bool
      aliases:
        description: Complete list of static addresses managed on the interface.
        type: list
        elements: dict
        suboptions:
          type:
            description: Address family.
            type: str
            choices: [INET, INET6]
            required: true
          address:
            description: IP address without a prefix.
            type: str
            required: true
          netmask:
            description: Prefix length.
            type: int
            required: true
      mtu:
        description: Interface MTU, or C(null) when unmanaged.
        type: int
  rollback:
    description: Enable automatic TrueNAS rollback if the commit is not confirmed.
    type: bool
    default: true
  checkin_timeout:
    description: Seconds before TrueNAS rolls back an unconfirmed commit.
    type: int
    default: 60
notes:
  - Supports check mode.
  - Interfaces must already exist; this module intentionally does not create
    physical interfaces, bridges, VLANs or link aggregations.
version_added: 2.1.0
'''

EXAMPLES = r'''
- name: Configure WAN and LAN together
  arensb.truenas.network_interfaces:
    interfaces:
      - name: ens18
        description: WAN
        ipv4_dhcp: false
        ipv6_auto: false
        aliases:
          - type: INET
            address: 192.168.2.6
            netmask: 24
        mtu: 1500
      - name: ens19
        description: LAN
        ipv4_dhcp: false
        ipv6_auto: false
        aliases:
          - type: INET
            address: 10.2.2.6
            netmask: 24
        mtu: 1500
'''

RETURN = r'''
changed_interfaces:
  description: Interface names that were or would be changed.
  returned: always
  type: list
  elements: str
changed_fields:
  description: Managed fields changed for each interface.
  returned: always
  type: dict
'''

from ansible.module_utils.basic import AnsibleModule
from ..module_utils.middleware import MiddleWare as MW


MANAGED_FIELDS = ('description', 'ipv4_dhcp', 'ipv6_auto', 'aliases', 'mtu')


def normalize_aliases(aliases):
    """Drop computed middleware fields and make ordering insignificant."""
    normalized = [
        {
            'type': alias['type'],
            'address': alias['address'],
            'netmask': alias['netmask'],
        }
        for alias in aliases
    ]
    return sorted(
        normalized,
        key=lambda alias: (
            alias['type'], alias['address'], alias['netmask']))


def main():
    alias_spec = dict(
        type=dict(type='str', choices=['INET', 'INET6'], required=True),
        address=dict(type='str', required=True),
        netmask=dict(type='int', required=True),
    )
    interface_spec = dict(
        name=dict(type='str', required=True),
        description=dict(type='str'),
        ipv4_dhcp=dict(type='bool'),
        ipv6_auto=dict(type='bool'),
        aliases=dict(type='list', elements='dict', options=alias_spec),
        mtu=dict(type='int'),
    )
    module = AnsibleModule(
        argument_spec=dict(
            interfaces=dict(
                type='list', elements='dict', options=interface_spec,
                required=True),
            rollback=dict(type='bool', default=True),
            checkin_timeout=dict(type='int', default=60),
        ),
        supports_check_mode=True,
    )

    desired_interfaces = module.params['interfaces']
    names = [interface['name'] for interface in desired_interfaces]
    if len(names) != len(set(names)):
        module.fail_json(msg='Each interface name must be unique.')

    mw = MW.client()
    try:
        current_interfaces = mw.call('interface.query')
    except Exception as e:
        module.fail_json(msg=f'Error looking up network interfaces: {e}')

    current_by_name = {
        interface['name']: interface for interface in current_interfaces
    }
    updates = {}
    changed_fields = {}
    for desired in desired_interfaces:
        name = desired['name']
        current = current_by_name.get(name)
        if current is None:
            module.fail_json(msg=f'Network interface {name} does not exist.')

        update = {}
        for field in MANAGED_FIELDS:
            value = desired[field]
            if value is None:
                continue
            current_value = current.get(field)
            if field == 'aliases':
                value = normalize_aliases(value)
                current_value = normalize_aliases(current_value or [])
            if current_value != value:
                update[field] = value
        if update:
            updates[name] = update
            changed_fields[name] = sorted(update.keys())

    result = {
        'changed': bool(updates),
        'changed_interfaces': sorted(updates.keys()),
        'changed_fields': changed_fields,
    }
    if not updates or module.check_mode:
        module.exit_json(**result)

    try:
        for name, update in updates.items():
            mw.call('interface.update', name, update)
        mw.call(
            'interface.commit',
            {
                'rollback': module.params['rollback'],
                'checkin_timeout': module.params['checkin_timeout'],
            })
        if module.params['rollback']:
            mw.call('interface.checkin')
    except Exception as e:
        try:
            mw.call('interface.rollback')
        except Exception:
            pass
        module.fail_json(
            msg=(f'Error applying network interface configuration; '
                 f'rollback requested: {e}'), **result)

    module.exit_json(**result)


if __name__ == '__main__':
    main()
