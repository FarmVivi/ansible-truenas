# -*- coding: utf-8 -*-

from ansible.errors import AnsibleActionFail
from ansible.plugins.action import ActionBase
from ..modules.ssh_configuration import argument_spec


class ActionModule(ActionBase):
    def run(self, tmp=None, task_vars=None):
        result = super(ActionModule, self).run(tmp, task_vars)
        self.validate_argument_spec(argument_spec=argument_spec)
        subtask = self._task.copy()
        host_keys = dict(subtask.args.get('host_keys') or {})

        for algorithm, key_spec in host_keys.items():
            key_spec = dict(key_spec or {})
            for file_option, content_option in (
                    ('private_keyfile', 'private_key'),
                    ('public_keyfile', 'public_key')):
                path = key_spec.pop(file_option, None)
                if path is None:
                    continue
                try:
                    with open(path, 'rt') as key_file:
                        key_spec[content_option] = key_file.read()
                except Exception as exc:
                    raise AnsibleActionFail(
                        f"Error opening '{file_option}: {path}': {exc}")
            host_keys[algorithm] = key_spec

        subtask.args['host_keys'] = host_keys
        return self._execute_module(
            module_name='arensb.truenas.ssh_configuration',
            module_args=subtask.args,
            task_vars=task_vars,
        )
