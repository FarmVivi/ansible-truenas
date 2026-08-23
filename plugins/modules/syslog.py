#!/usr/bin/python
# -*- coding: utf-8 -*-
__metaclass__ = type

DOCUMENTATION = r'''
---
module: syslog
short_description: Manage TrueNAS remote syslog forwarding
description:
  - Idempotently manages the remote syslog settings exposed by
    C(system.advanced.update).
  - Resolves a TLS certificate by its TrueNAS certificate name, rather than
    requiring an installation-specific numeric identifier.
options:
  servers:
    description:
      - Remote syslog servers to forward to. TrueNAS accepts at most two.
      - The middleware replaces the whole list on update, so this option is
        declarative - servers absent from the list are removed.
      - Omit the option entirely to leave the current list untouched; pass an
        empty list to disable remote forwarding.
    type: list
    elements: dict
    suboptions:
      host:
        description:
          - Hostname or IP address of the remote syslog server.
          - A non-standard port is appended with a colon, for example
            C(loghost:1514). TrueNAS defaults to port 514 for UDP and TCP
            (RFC 3164) and 6514 for TLS (RFC 5425).
        type: str
        required: true
      transport:
        description: Transport protocol used to reach the server.
        type: str
        choices: [UDP, TCP, TLS]
        default: UDP
      tls_certificate:
        description:
          - Name of an existing TrueNAS certificate used for TLS transport.
          - Only meaningful when I(transport) is C(TLS).
        type: str
  level:
    description: Minimum severity forwarded to the remote servers.
    type: str
    choices: [F_EMERG, F_ALERT, F_CRIT, F_ERR, F_WARNING, F_NOTICE, F_INFO, F_DEBUG]
  use_fqdn:
    description: Send the fully-qualified domain name instead of the short hostname.
    type: bool
  audit:
    description: Also forward audit records to the remote servers.
    type: bool
notes:
  - Supports check mode.
version_added: 2.1.0
'''

EXAMPLES = r'''
- name: Forward logs to a collector over TCP on a non-standard port
  arensb.truenas.syslog:
    servers:
      - host: 10.2.2.2:1514
        transport: TCP
    level: F_INFO

- name: Forward over TLS, resolving the certificate by name
  arensb.truenas.syslog:
    servers:
      - host: loghost.example.com
        transport: TLS
        tls_certificate: scipio-loghost
    audit: true

- name: Disable remote forwarding
  arensb.truenas.syslog:
    servers: []
'''

RETURN = r'''
changed_fields:
  description: Settings that were, or would be, changed.
  returned: always
  type: list
  elements: str
'''

from ansible.module_utils.basic import AnsibleModule
from ..module_utils.middleware import MiddleWare as MW


# Simple scalars, compared and sent as-is. Keyed by module option name so the
# public interface stays readable while matching the middleware field names.
SCALAR_OPTIONS = {
    'level': 'sysloglevel',
    'use_fqdn': 'fqdn_syslog',
    'audit': 'syslog_audit',
}


def _resolve_certificate(module, mw, name):
    """Return the numeric id of the certificate called `name`."""
    try:
        certificates = mw.call('certificate.query', [['name', '=', name]])
    except Exception as e:
        module.fail_json(msg=f'Error looking up certificate {name}: {e}')

    if len(certificates) != 1:
        module.fail_json(
            msg=(f'Expected exactly one certificate named {name}, '
                 f'found {len(certificates)}.'))
    return certificates[0]['id']


def _normalize_current(entry):
    """Reduce a middleware entry to the fields this module manages.

    The middleware returns the certificate as an expanded object (or null);
    only its id is comparable with what we send.
    """
    certificate = entry.get('tls_certificate')
    if isinstance(certificate, dict):
        certificate = certificate.get('id')
    return {
        'host': entry.get('host'),
        'transport': entry.get('transport') or 'UDP',
        'tls_certificate': certificate,
    }


def main():
    module = AnsibleModule(
        argument_spec=dict(
            servers=dict(
                type='list', elements='dict',
                options=dict(
                    host=dict(type='str', required=True),
                    transport=dict(
                        type='str', choices=['UDP', 'TCP', 'TLS'],
                        default='UDP'),
                    tls_certificate=dict(type='str'),
                ),
            ),
            level=dict(
                type='str',
                choices=['F_EMERG', 'F_ALERT', 'F_CRIT', 'F_ERR',
                         'F_WARNING', 'F_NOTICE', 'F_INFO', 'F_DEBUG']),
            use_fqdn=dict(type='bool'),
            audit=dict(type='bool'),
        ),
        supports_check_mode=True,
    )

    mw = MW.client()
    result = {'changed': False, 'changed_fields': []}

    try:
        current = mw.call('system.advanced.config')
    except Exception as e:
        module.fail_json(msg=f'Error looking up system advanced settings: {e}')

    update = {}

    servers = module.params['servers']
    if servers is not None:
        if len(servers) > 2:
            module.fail_json(
                msg=(f'TrueNAS accepts at most two remote syslog servers, '
                     f'{len(servers)} were given.'))

        desired = []
        for server in servers:
            entry = {
                'host': server['host'],
                'transport': server['transport'],
                'tls_certificate': None,
            }
            certificate_name = server.get('tls_certificate')
            if certificate_name is not None:
                entry['tls_certificate'] = _resolve_certificate(
                    module, mw, certificate_name)
            desired.append(entry)

        existing = [_normalize_current(e)
                    for e in (current.get('syslogservers') or [])]
        if existing != desired:
            # The middleware overwrites the whole array, so the payload is the
            # complete desired list rather than a delta.
            update['syslogservers'] = [
                {k: v for k, v in e.items() if v is not None} for e in desired]

    for option, field in SCALAR_OPTIONS.items():
        value = module.params[option]
        if value is not None and current.get(field) != value:
            update[field] = value

    result['changed_fields'] = sorted(update.keys())
    if not update:
        module.exit_json(**result)

    result['changed'] = True
    if module.check_mode:
        module.exit_json(**result)

    try:
        mw.call('system.advanced.update', update)
    except Exception as e:
        module.fail_json(
            msg=(f'Error updating syslog settings '
                 f'{result["changed_fields"]}: {e}'))

    module.exit_json(**result)


if __name__ == '__main__':
    main()
