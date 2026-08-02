#!/usr/bin/python
# -*- coding: utf-8 -*-
__metaclass__ = type

DOCUMENTATION = r'''
---
module: ssh_configuration
short_description: Manage the TrueNAS SSH service configuration
description:
  - Idempotently manages C(ssh.update), including persistent SSH host keys.
options:
  passwordauth:
    type: bool
  tcpport:
    type: int
  bindiface:
    type: list
    elements: str
  host_keys:
    type: dict
    description:
      - Mapping of SSH algorithms to private/public key material.
      - Supported keys are C(dsa), C(ecdsa), C(ed25519), and C(rsa).
notes:
  - Use the action plugin C(private_keyfile)/C(public_keyfile) inputs to read
    key material from the Ansible controller.
  - Supports check mode and never returns private key material.
version_added: 2.1.0
'''

EXAMPLES = r'''
- name: Manage persistent SSH identities
  arensb.truenas.ssh_configuration:
    passwordauth: false
    host_keys:
      ed25519:
        private_keyfile: files/ssh_host_ed25519_key
        public_keyfile: files/ssh_host_ed25519_key.pub
'''

from ansible.module_utils.basic import AnsibleModule
from ..module_utils.middleware import MiddleWare as MW


ALGORITHMS = ('dsa', 'ecdsa', 'ed25519', 'rsa')

HOST_KEY_OPTIONS = dict(
    private_key=dict(type='str', no_log=True),
    public_key=dict(type='str'),
    private_keyfile=dict(type='path'),
    public_keyfile=dict(type='path'),
)

argument_spec = dict(
    passwordauth=dict(type='bool'),
    tcpport=dict(type='int'),
    bindiface=dict(type='list', elements='str'),
    host_keys=dict(
        type='dict',
        options={algorithm: dict(type='dict', options=HOST_KEY_OPTIONS)
                 for algorithm in ALGORITHMS},
    ),
)


def main():
    module = AnsibleModule(argument_spec=argument_spec, supports_check_mode=True)
    mw = MW.client()

    try:
        current = mw.call('ssh.config')
    except Exception as exc:
        module.fail_json(msg=f'Error looking up SSH configuration: {exc}')

    update = {}
    for option in ('passwordauth', 'tcpport', 'bindiface'):
        desired = module.params[option]
        if desired is not None and current.get(option) != desired:
            update[option] = desired

    for algorithm, keys in (module.params['host_keys'] or {}).items():
        if keys is None:
            continue
        for source_name, suffix in (('private_key', 'key'),
                                    ('public_key', 'key_pub')):
            desired = keys.get(source_name)
            if desired is None:
                continue
            field = f'host_{algorithm}_{suffix}'
            if (current.get(field) or '').strip() != desired.strip():
                update[field] = desired

    changed_fields = sorted(update.keys())
    if not update or module.check_mode:
        module.exit_json(changed=bool(update), changed_fields=changed_fields)

    try:
        mw.call('ssh.update', update)
    except Exception as exc:
        module.fail_json(
            msg=f'Error updating SSH configuration fields {changed_fields}: {exc}')

    module.exit_json(changed=True, changed_fields=changed_fields)


if __name__ == '__main__':
    main()
