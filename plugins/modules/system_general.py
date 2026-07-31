#!/usr/bin/python
# -*- coding: utf-8 -*-
__metaclass__ = type

DOCUMENTATION = r'''
---
module: system_general
short_description: Manage TrueNAS system general and web UI settings
description:
  - Idempotently manages settings exposed by C(system.general.update).
  - Resolves the web UI certificate by its TrueNAS certificate name, rather
    than requiring an installation-specific numeric identifier.
  - Does not return the full middleware configuration because the expanded
    certificate object can contain private key material.
options:
  ui_certificate:
    description: Name of an existing TrueNAS certificate to use for the web UI.
    type: str
  ui_httpsport:
    description: HTTPS port for the web UI.
    type: int
  ui_httpsredirect:
    description: Redirect HTTP requests to HTTPS.
    type: bool
  ui_httpsprotocols:
    description: Enabled TLS protocol versions.
    type: list
    elements: str
    choices: [TLSv1, TLSv1.1, TLSv1.2, TLSv1.3]
  ui_port:
    description: HTTP port for the web UI.
    type: int
  ui_address:
    description: IPv4 addresses on which the web UI listens.
    type: list
    elements: str
  ui_v6address:
    description: IPv6 addresses on which the web UI listens.
    type: list
    elements: str
  ui_allowlist:
    description: Addresses and networks allowed to access the API and web UI.
    type: list
    elements: str
  ui_consolemsg:
    description: Show console messages in the web UI.
    type: bool
  ui_x_frame_options:
    description: Value of the web UI X-Frame-Options policy.
    type: str
    choices: [SAMEORIGIN, DENY, ALLOW_ALL]
  kbdmap:
    description: System keyboard layout mapping.
    type: str
  timezone:
    description: System timezone identifier.
    type: str
  usage_collection:
    description: Enable TrueNAS usage data collection.
    type: bool
  ds_auth:
    description: Allow privileged directory-service users to use UI and API.
    type: bool
  ui_restart_delay:
    description:
      - Seconds before TrueNAS restarts the web UI to apply changed UI settings.
      - Omit this option to leave the restart under caller control.
    type: int
  rollback_timeout:
    description:
      - Seconds after which TrueNAS rolls back an unconfirmed UI change.
      - The caller must invoke C(system.general.checkin) separately after
        verifying connectivity.
    type: int
notes:
  - Supports check mode.
  - C(ui_restart_delay) and C(rollback_timeout) are sent only when a persistent
    setting changes and are not themselves compared for idempotence.
version_added: 2.1.0
'''

EXAMPLES = r'''
- name: Harden the TrueNAS web UI and activate a managed certificate
  arensb.truenas.system_general:
    ui_certificate: scipio-library-skaro
    timezone: Europe/Paris
    ui_httpsredirect: true
    ui_httpsprotocols:
      - TLSv1.2
      - TLSv1.3
    ui_restart_delay: 2
'''

RETURN = r'''
changed_fields:
  description: Persistent settings that were or would be changed.
  returned: always
  type: list
  elements: str
certificate_id:
  description: Resolved numeric certificate identifier, when requested.
  returned: when ui_certificate is set
  type: int
'''

from ansible.module_utils.basic import AnsibleModule
from ..module_utils.middleware import MiddleWare as MW


PERSISTENT_OPTIONS = (
    'ui_httpsport',
    'ui_httpsredirect',
    'ui_httpsprotocols',
    'ui_port',
    'ui_address',
    'ui_v6address',
    'ui_allowlist',
    'ui_consolemsg',
    'ui_x_frame_options',
    'kbdmap',
    'timezone',
    'usage_collection',
    'ds_auth',
)


def main():
    module = AnsibleModule(
        argument_spec=dict(
            ui_certificate=dict(type='str'),
            ui_httpsport=dict(type='int'),
            ui_httpsredirect=dict(type='bool'),
            ui_httpsprotocols=dict(
                type='list',
                elements='str',
                choices=['TLSv1', 'TLSv1.1', 'TLSv1.2', 'TLSv1.3'],
            ),
            ui_port=dict(type='int'),
            ui_address=dict(type='list', elements='str'),
            ui_v6address=dict(type='list', elements='str'),
            ui_allowlist=dict(type='list', elements='str'),
            ui_consolemsg=dict(type='bool'),
            ui_x_frame_options=dict(
                type='str', choices=['SAMEORIGIN', 'DENY', 'ALLOW_ALL']),
            kbdmap=dict(type='str'),
            timezone=dict(type='str'),
            usage_collection=dict(type='bool'),
            ds_auth=dict(type='bool'),
            ui_restart_delay=dict(type='int'),
            rollback_timeout=dict(type='int'),
        ),
        supports_check_mode=True,
    )

    mw = MW.client()
    result = {'changed': False, 'changed_fields': []}

    try:
        current = mw.call('system.general.config')
    except Exception as e:
        module.fail_json(msg=f'Error looking up system general settings: {e}')

    update = {}
    certificate_name = module.params['ui_certificate']
    if certificate_name is not None:
        try:
            certificates = mw.call(
                'certificate.query', [['name', '=', certificate_name]])
        except Exception as e:
            module.fail_json(
                msg=f'Error looking up certificate {certificate_name}: {e}')

        if len(certificates) != 1:
            module.fail_json(
                msg=(f'Expected exactly one certificate named '
                     f'{certificate_name}, found {len(certificates)}.'))

        certificate_id = certificates[0]['id']
        result['certificate_id'] = certificate_id
        current_certificate = current.get('ui_certificate') or {}
        if current_certificate.get('id') != certificate_id:
            update['ui_certificate'] = certificate_id

    for option in PERSISTENT_OPTIONS:
        desired = module.params[option]
        if desired is not None and current.get(option) != desired:
            update[option] = desired

    result['changed_fields'] = sorted(update.keys())
    if not update:
        module.exit_json(**result)

    result['changed'] = True
    if module.check_mode:
        module.exit_json(**result)

    for action_option in ('ui_restart_delay', 'rollback_timeout'):
        if module.params[action_option] is not None:
            update[action_option] = module.params[action_option]

    try:
        mw.call('system.general.update', update)
    except Exception as e:
        module.fail_json(
            msg=(f'Error updating system general fields '
                 f'{result["changed_fields"]}: {e}'))

    module.exit_json(**result)


if __name__ == '__main__':
    main()
