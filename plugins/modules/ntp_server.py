#!/usr/bin/python
# -*- coding: utf-8 -*-
__metaclass__ = type

DOCUMENTATION = r'''
---
module: ntp_server
short_description: Manage TrueNAS NTP servers
description:
  - Creates, updates and deletes entries from C(system.ntpserver).
  - The server address is the stable resource identifier.
options:
  address:
    description: Hostname or IP address of the NTP server.
    type: str
    required: true
  state:
    description: Whether the NTP server should exist.
    type: str
    choices: [absent, present]
    default: present
  burst:
    description: Send a burst when the server is reachable.
    type: bool
  iburst:
    description: Speed up initial synchronization.
    type: bool
  prefer:
    description: Prefer this server when candidates are otherwise equal.
    type: bool
  minpoll:
    description: Minimum polling interval as a base-2 exponent.
    type: int
  maxpoll:
    description: Maximum polling interval as a base-2 exponent.
    type: int
  force:
    description: Accept the server even if it is currently unreachable.
    type: bool
notes:
  - Supports check mode.
version_added: 2.1.0
'''

EXAMPLES = r'''
- name: Use the site's internal NTP server
  arensb.truenas.ntp_server:
    address: 10.2.2.5
    iburst: true
    prefer: true
    force: true

- name: Remove a public pool entry
  arensb.truenas.ntp_server:
    address: 0.debian.pool.ntp.org
    state: absent
'''

RETURN = r'''
changed_fields:
  description: Settings that were or would be changed.
  returned: when an existing entry is updated
  type: list
  elements: str
'''

from ansible.module_utils.basic import AnsibleModule
from ..module_utils.middleware import MiddleWare as MW


OPTIONS = ('burst', 'iburst', 'prefer', 'minpoll', 'maxpoll')


def main():
    module = AnsibleModule(
        argument_spec=dict(
            address=dict(type='str', required=True),
            state=dict(type='str', choices=['absent', 'present'],
                       default='present'),
            burst=dict(type='bool'),
            iburst=dict(type='bool'),
            prefer=dict(type='bool'),
            minpoll=dict(type='int'),
            maxpoll=dict(type='int'),
            force=dict(type='bool'),
        ),
        supports_check_mode=True,
    )

    mw = MW.client()
    address = module.params['address']
    state = module.params['state']
    try:
        matches = mw.call(
            'system.ntpserver.query', [['address', '=', address]])
    except Exception as e:
        module.fail_json(msg=f'Error looking up NTP server {address}: {e}')

    if len(matches) > 1:
        module.fail_json(msg=f'Multiple NTP servers use address {address}.')
    current = matches[0] if matches else None

    if state == 'absent':
        if current is None:
            module.exit_json(changed=False)
        if module.check_mode:
            module.exit_json(changed=True)
        try:
            mw.call('system.ntpserver.delete', current['id'])
        except Exception as e:
            module.fail_json(msg=f'Error deleting NTP server {address}: {e}')
        module.exit_json(changed=True)

    desired = {'address': address}
    for option in OPTIONS:
        if module.params[option] is not None:
            desired[option] = module.params[option]
    if current is None and module.params['force'] is not None:
        desired['force'] = module.params['force']

    if current is None:
        if module.check_mode:
            module.exit_json(changed=True)
        try:
            mw.call('system.ntpserver.create', desired)
        except Exception as e:
            module.fail_json(msg=f'Error creating NTP server {address}: {e}')
        module.exit_json(changed=True)

    update = {
        option: desired[option]
        for option in OPTIONS
        if option in desired and current.get(option) != desired[option]
    }
    result = {
        'changed': bool(update),
        'changed_fields': sorted(update.keys()),
    }
    if not update or module.check_mode:
        module.exit_json(**result)

    try:
        mw.call('system.ntpserver.update', current['id'], update)
    except Exception as e:
        module.fail_json(
            msg=(f'Error updating NTP server {address} fields '
                 f'{result["changed_fields"]}: {e}'))
    module.exit_json(**result)


if __name__ == '__main__':
    main()
