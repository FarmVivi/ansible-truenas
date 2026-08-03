#!/usr/bin/python
# -*- coding: utf-8 -*-
__metaclass__ = type

DOCUMENTATION = r'''
---
module: alertservice
short_description: Manage TrueNAS alert services
description:
  - Creates, updates and deletes entries from C(alertservice), the list of
    destinations TrueNAS sends its alerts to.
  - The service name is the stable resource identifier. TrueNAS ships with a
    service named C(Mail); keeping that name avoids creating a duplicate
    alongside it.
  - This is distinct from C(mail.config), the single SMTP relay every
    notification goes through. A destination is not a relay.
options:
  name:
    description: Human-readable name of the alert service.
    type: str
    required: true
  state:
    description: Whether the alert service should exist.
    type: str
    choices: [absent, present]
    default: present
  type:
    description:
      - Service type, which selects the shape of I(attributes).
      - Required when I(state=present).
    type: str
  attributes:
    description:
      - Type-specific settings, for example C(email) for a C(Mail) service.
      - The C(type) key is added automatically from I(type) and must not be
        repeated here.
    type: dict
    default: {}
  level:
    description: Minimum severity that reaches this destination.
    type: str
    choices: [INFO, NOTICE, WARNING, ERROR, CRITICAL, ALERT, EMERGENCY]
  enabled:
    description: Whether the destination receives alerts at all.
    type: bool
notes:
  - Supports check mode.
version_added: 2.1.0
'''

EXAMPLES = r'''
- name: Send warnings and above to the on-call mailbox
  arensb.truenas.alertservice:
    name: Mail
    type: Mail
    attributes:
      email: ops@example.org
    level: WARNING
    enabled: true

- name: Stop alerting a former operator
  arensb.truenas.alertservice:
    name: Mail Archive
    state: absent
'''

RETURN = r'''
changed_fields:
  description: Settings that were or would be changed.
  returned: when an existing alert service is updated
  type: list
  elements: str
'''

from ansible.module_utils.basic import AnsibleModule
from ..module_utils.middleware import MiddleWare as MW


OPTIONS = ('level', 'enabled')


def main():
    module = AnsibleModule(
        argument_spec=dict(
            name=dict(type='str', required=True),
            state=dict(type='str', choices=['absent', 'present'],
                       default='present'),
            type=dict(type='str'),
            attributes=dict(type='dict', default={}),
            level=dict(type='str',
                       choices=['INFO', 'NOTICE', 'WARNING', 'ERROR',
                                'CRITICAL', 'ALERT', 'EMERGENCY']),
            enabled=dict(type='bool'),
        ),
        required_if=[('state', 'present', ('type',))],
        supports_check_mode=True,
    )

    mw = MW.client()
    name = module.params['name']
    state = module.params['state']

    try:
        matches = mw.call('alertservice.query', [['name', '=', name]])
    except Exception as e:
        module.fail_json(msg=f'Error looking up alert service {name}: {e}')

    if len(matches) > 1:
        module.fail_json(msg=f'Multiple alert services are named {name}.')
    current = matches[0] if matches else None

    if state == 'absent':
        if current is None:
            module.exit_json(changed=False)
        if module.check_mode:
            module.exit_json(changed=True)
        try:
            mw.call('alertservice.delete', current['id'])
        except Exception as e:
            module.fail_json(msg=f'Error deleting alert service {name}: {e}')
        module.exit_json(changed=True)

    if 'type' in module.params['attributes']:
        module.fail_json(
            msg=("'type' belongs to the 'type' option, not to 'attributes'; "
                 'the module adds it to the payload itself.'))

    attributes = dict(module.params['attributes'])
    attributes['type'] = module.params['type']
    desired = {'name': name, 'attributes': attributes}
    for option in OPTIONS:
        if module.params[option] is not None:
            desired[option] = module.params[option]

    if current is None:
        if module.check_mode:
            module.exit_json(changed=True)
        try:
            mw.call('alertservice.create', desired)
        except Exception as e:
            module.fail_json(msg=f'Error creating alert service {name}: {e}')
        module.exit_json(changed=True)

    update = {
        option: desired[option]
        for option in OPTIONS
        if option in desired and current.get(option) != desired[option]
    }
    # Only the declared attributes are compared: middlewared echoes back
    # defaults the caller never set, and treating those as drift would make
    # every run report a change.
    current_attributes = current.get('attributes') or {}
    if any(current_attributes.get(key) != value
           for key, value in attributes.items()):
        update['attributes'] = attributes

    result = {
        'changed': bool(update),
        'changed_fields': sorted(update.keys()),
    }
    if not update or module.check_mode:
        module.exit_json(**result)

    try:
        mw.call('alertservice.update', current['id'], update)
    except Exception as e:
        module.fail_json(
            msg=(f'Error updating alert service {name} fields '
                 f'{result["changed_fields"]}: {e}'))
    module.exit_json(**result)


if __name__ == '__main__':
    main()
