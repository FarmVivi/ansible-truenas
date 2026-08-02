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

import base64
import os
import tempfile

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
    host_key_update = {}
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
            path = f'/etc/ssh/ssh_host_{algorithm}_key'
            if source_name == 'public_key':
                path += '.pub'
            try:
                stored = base64.b64decode(current.get(field) or '').decode()
            except Exception:
                stored = ''
            try:
                with open(path, 'rt') as key_file:
                    runtime = key_file.read()
            except FileNotFoundError:
                runtime = ''
            if stored.strip() != desired.strip() or runtime.strip() != desired.strip():
                host_key_update[path] = {
                    'content': desired,
                    'mode': 0o600 if source_name == 'private_key' else 0o644,
                }

    changed_fields = sorted(
        list(update.keys())
        + [os.path.basename(path) for path in host_key_update]
    )
    if not update and not host_key_update:
        module.exit_json(changed=False, changed_fields=[])
    if module.check_mode:
        module.exit_json(changed=True, changed_fields=changed_fields)

    try:
        if host_key_update:
            for path, key in host_key_update.items():
                directory = os.path.dirname(path)
                fd, temporary_path = tempfile.mkstemp(dir=directory)
                try:
                    with os.fdopen(fd, 'w') as key_file:
                        key_file.write(key['content'])
                    os.chmod(temporary_path, key['mode'])
                    os.replace(temporary_path, path)
                finally:
                    if os.path.exists(temporary_path):
                        os.unlink(temporary_path)
            # TrueNAS' own private helper base64-encodes /etc/ssh host keys
            # into the encrypted services.ssh datastore row. They are then
            # restored across upgrades and reboots by the normal boot flow.
            mw.call('ssh.save_keys')
        if update:
            # ssh.update reloads the service and activates the files staged
            # immediately above.
            mw.call('ssh.update', update)
        elif host_key_update:
            mw.call('service.restart', 'ssh')
    except Exception as exc:
        module.fail_json(
            msg=f'Error updating SSH configuration fields {changed_fields}: {exc}')

    module.exit_json(changed=True, changed_fields=changed_fields)


if __name__ == '__main__':
    main()
