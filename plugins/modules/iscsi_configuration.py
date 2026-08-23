#!/usr/bin/python
# -*- coding: utf-8 -*-
__metaclass__ = type

DOCUMENTATION = r'''
---
module: iscsi_configuration
short_description: Manage a TrueNAS iSCSI configuration graph
description:
  - Idempotently manages global settings, portals, initiator groups, targets,
    extents and target-to-extent associations.
  - Human-readable portal comments, initiator comments and resource names are
    resolved to middleware numeric IDs.
  - Resources not listed are left untouched; deletion is intentionally not
    inferred from absence.
options:
  global_settings:
    type: dict
    description: Managed global iSCSI settings.
  portals:
    type: list
    elements: dict
    description: Portals identified by their unique comment.
  initiators:
    type: list
    elements: dict
    description: Authorized initiator groups identified by unique comment.
  auths:
    type: list
    elements: dict
    description:
      - CHAP credentials ("Authorized Access" in the web UI), identified by
        their unique C(user).
      - Several credentials may share a C(tag); a target group referencing that
        tag accepts any of them.
  extents:
    type: list
    elements: dict
    description: Extents identified by unique name.
  targets:
    type: list
    elements: dict
    description: Targets identified by unique name.
  associations:
    type: list
    elements: dict
    description: Target-to-extent associations referenced by names.
notes:
  - Supports check mode.
  - A target group references a credential by its C(user), which is resolved to
    the underlying C(tag). The middleware matches C(groups[].auth) against the
    credential B(tag), not against its row id, despite what the API reference
    suggests.
  - Secrets are marked C(no_log). Idempotency relies on C(iscsi.auth.query)
    returning them in the clear; should a future release redact them, the
    credential would be rewritten on every run (reported as changed).
version_added: 2.1.0
'''

EXAMPLES = r'''
- name: Export a zvol to one initiator
  arensb.truenas.iscsi_configuration:
    global_settings:
      basename: iqn.2005-10.org.freenas.ctl
      isns_servers: []
      alua: false
    portals:
      - comment: storage-lan
        listen: [10.2.2.6]
    initiators:
      - comment: kubernetes-node
        initiators: [iqn.2026-04.home.example:node-01]
    auths:
      - tag: 1
        user: bulk-01
        secret: "{{ vault_iscsi_secret }}"
        peeruser: nas-bulk-01
        peersecret: "{{ vault_iscsi_peersecret }}"
    extents:
      - name: bulk-01
        disk: zvol/tank/bulk-01
        blocksize: 4096
    targets:
      - name: bulk-01
        auth_networks: [10.2.2.30/32]
        groups:
          - portal: storage-lan
            initiator: kubernetes-node
            authmethod: CHAP_MUTUAL
            auth: bulk-01
    associations:
      - target: bulk-01
        extent: bulk-01
        lunid: 0
'''

RETURN = r'''
changed_resources:
  description: Resources that were or would be created or updated.
  returned: always
  type: list
  elements: str
'''

from ansible.module_utils.basic import AnsibleModule
from ..module_utils.middleware import MiddleWare as MW


def wanted_fields(desired, current, fields):
    return {
        field: desired[field]
        for field in fields
        if desired.get(field) is not None and current.get(field) != desired[field]
    }


def unique_map(module, resources, key, kind):
    mapped = {}
    for resource in resources:
        value = resource.get(key)
        if not value:
            module.fail_json(msg=f'Every {kind} requires a non-empty {key}.')
        if value in mapped:
            module.fail_json(msg=f'Duplicate {kind} {key}: {value}.')
        mapped[value] = resource
    return mapped


def main():
    portal_spec = dict(
        comment=dict(type='str', required=True),
        listen=dict(type='list', elements='str', required=True),
    )
    initiator_spec = dict(
        comment=dict(type='str', required=True),
        initiators=dict(type='list', elements='str', required=True),
    )
    extent_spec = dict(
        name=dict(type='str', required=True),
        type=dict(type='str', choices=['DISK', 'FILE'], default='DISK'),
        disk=dict(type='str'),
        path=dict(type='str'),
        filesize=dict(type='str'),
        blocksize=dict(type='int', choices=[512, 1024, 2048, 4096]),
        pblocksize=dict(type='bool'),
        avail_threshold=dict(type='int'),
        comment=dict(type='str'),
        insecure_tpc=dict(type='bool'),
        xen=dict(type='bool'),
        rpm=dict(type='str', choices=['UNKNOWN', 'SSD', '5400', '7200',
                                      '10000', '15000']),
        ro=dict(type='bool'),
        enabled=dict(type='bool'),
        product_id=dict(type='str'),
    )
    auth_spec = dict(
        tag=dict(type='int', required=True),
        user=dict(type='str', required=True),
        secret=dict(type='str', required=True, no_log=True),
        peeruser=dict(type='str'),
        peersecret=dict(type='str', no_log=True),
        discovery_auth=dict(type='str', default='NONE',
                            choices=['NONE', 'CHAP', 'CHAP_MUTUAL']),
    )
    group_spec = dict(
        portal=dict(type='str', required=True),
        initiator=dict(type='str'),
        authmethod=dict(type='str', default='NONE',
                        choices=['NONE', 'CHAP', 'CHAP_MUTUAL']),
        auth=dict(type='str'),
    )
    target_spec = dict(
        name=dict(type='str', required=True),
        alias=dict(type='str'),
        mode=dict(type='str', choices=['ISCSI', 'FC', 'BOTH'], default='ISCSI'),
        groups=dict(type='list', elements='dict', options=group_spec,
                    required=True),
        auth_networks=dict(type='list', elements='str'),
    )
    association_spec = dict(
        target=dict(type='str', required=True),
        extent=dict(type='str', required=True),
        lunid=dict(type='int', required=True),
    )
    module = AnsibleModule(
        argument_spec=dict(
            global_settings=dict(type='dict', options=dict(
                basename=dict(type='str'),
                isns_servers=dict(type='list', elements='str'),
                listen_port=dict(type='int'),
                pool_avail_threshold=dict(type='int'),
                alua=dict(type='bool'),
                iser=dict(type='bool'),
            ), default={}),
            portals=dict(type='list', elements='dict', options=portal_spec,
                         default=[]),
            initiators=dict(type='list', elements='dict',
                            options=initiator_spec, default=[]),
            auths=dict(type='list', elements='dict', options=auth_spec,
                       default=[], no_log=False),
            extents=dict(type='list', elements='dict', options=extent_spec,
                         default=[]),
            targets=dict(type='list', elements='dict', options=target_spec,
                         default=[]),
            associations=dict(type='list', elements='dict',
                              options=association_spec, default=[]),
        ),
        supports_check_mode=True,
    )

    mw = MW.client()
    changed = []

    def call(method, *args):
        try:
            return mw.call(method, *args)
        except Exception as error:
            module.fail_json(msg=f'Error calling {method}: {error}',
                             changed_resources=changed)

    desired_portals = unique_map(module, module.params['portals'],
                                 'comment', 'portal')
    desired_initiators = unique_map(module, module.params['initiators'],
                                    'comment', 'initiator group')
    desired_auths = unique_map(module, module.params['auths'],
                               'user', 'CHAP credential')
    desired_extents = unique_map(module, module.params['extents'],
                                 'name', 'extent')
    desired_targets = unique_map(module, module.params['targets'],
                                 'name', 'target')

    current_global = call('iscsi.global.config')
    global_update = wanted_fields(
        module.params['global_settings'], current_global,
        ('basename', 'isns_servers', 'listen_port', 'pool_avail_threshold',
         'alua', 'iser'))
    if global_update:
        changed.append('global')
        if not module.check_mode:
            call('iscsi.global.update', global_update)

    portals = call('iscsi.portal.query')
    portals_by_comment = unique_map(module, portals, 'comment', 'existing portal')
    for comment, desired in desired_portals.items():
        current = portals_by_comment.get(comment)
        payload = {
            'comment': comment,
            'listen': [{'ip': ip} for ip in desired['listen']],
        }
        if current is None:
            changed.append(f'portal:{comment}')
            if not module.check_mode:
                portals_by_comment[comment] = call('iscsi.portal.create', payload)
            continue
        current_listen = sorted(item['ip'] for item in current.get('listen', []))
        desired_listen = sorted(desired['listen'])
        update = {}
        if current_listen != desired_listen:
            update['listen'] = payload['listen']
        if update:
            changed.append(f'portal:{comment}')
            if not module.check_mode:
                call('iscsi.portal.update', current['id'], update)

    initiators = call('iscsi.initiator.query')
    initiators_by_comment = unique_map(
        module, initiators, 'comment', 'existing initiator group')
    for comment, desired in desired_initiators.items():
        current = initiators_by_comment.get(comment)
        payload = {'comment': comment, 'initiators': desired['initiators']}
        if current is None:
            changed.append(f'initiator:{comment}')
            if not module.check_mode:
                initiators_by_comment[comment] = call(
                    'iscsi.initiator.create', payload)
            continue
        update = {}
        if sorted(current.get('initiators', [])) != sorted(desired['initiators']):
            update['initiators'] = desired['initiators']
        if update:
            changed.append(f'initiator:{comment}')
            if not module.check_mode:
                call('iscsi.initiator.update', current['id'], update)

    # Reconciled before the targets that reference them, and identified by
    # `user`: the tag is a group number that several credentials may share, so
    # it cannot serve as a key.
    auths = call('iscsi.auth.query')
    auths_by_user = unique_map(module, auths, 'user', 'existing CHAP credential')
    auth_fields = ('tag', 'user', 'secret', 'peeruser', 'peersecret',
                   'discovery_auth')
    for user, desired in desired_auths.items():
        current = auths_by_user.get(user)
        payload = {field: desired[field] for field in auth_fields
                   if desired.get(field) is not None}
        if current is None:
            changed.append(f'auth:{user}')
            if not module.check_mode:
                auths_by_user[user] = call('iscsi.auth.create', payload)
            continue
        update = wanted_fields(desired, current, auth_fields)
        if update:
            changed.append(f'auth:{user}')
            if not module.check_mode:
                call('iscsi.auth.update', current['id'], update)

    extents = call('iscsi.extent.query')
    extents_by_name = unique_map(module, extents, 'name', 'existing extent')
    extent_fields = ('type', 'disk', 'path', 'filesize', 'blocksize',
                     'pblocksize', 'avail_threshold', 'comment', 'insecure_tpc',
                     'xen', 'rpm', 'ro', 'enabled', 'product_id')
    for name, desired in desired_extents.items():
        current = extents_by_name.get(name)
        payload = {'name': name}
        payload.update({field: desired[field] for field in extent_fields
                        if desired.get(field) is not None})
        if current is None:
            changed.append(f'extent:{name}')
            if not module.check_mode:
                extents_by_name[name] = call('iscsi.extent.create', payload)
            continue
        update = wanted_fields(desired, current, extent_fields)
        if update:
            changed.append(f'extent:{name}')
            if not module.check_mode:
                call('iscsi.extent.update', current['id'], update)

    targets = call('iscsi.target.query')
    targets_by_name = unique_map(module, targets, 'name', 'existing target')
    for name, desired in desired_targets.items():
        resolved_groups = []
        references_missing = False
        for group in desired['groups']:
            portal = portals_by_comment.get(group['portal'])
            initiator = (initiators_by_comment.get(group['initiator'])
                         if group.get('initiator') else None)
            auth = (auths_by_user.get(group['auth'])
                    if group.get('auth') else None)
            if (portal is None
                    or (group.get('initiator') and initiator is None)
                    or (group.get('auth') and auth is None)):
                references_missing = True
                continue
            if group['authmethod'] != 'NONE' and auth is None:
                module.fail_json(
                    msg=f'Target {name} requests {group["authmethod"]} without '
                        'naming a credential in `auth`.')
            resolved_groups.append({
                'portal': portal['id'],
                'initiator': initiator['id'] if initiator else None,
                'authmethod': group['authmethod'],
                # The middleware resolves this against the credential tag.
                'auth': auth['tag'] if auth else None,
            })
        current = targets_by_name.get(name)
        if references_missing and module.check_mode:
            changed.append(f'target:{name}')
            continue
        if references_missing:
            module.fail_json(msg=f'Target {name} references an unknown group.')
        payload = {'name': name, 'groups': resolved_groups}
        for field in ('alias', 'mode', 'auth_networks'):
            if desired.get(field) is not None:
                payload[field] = desired[field]
        if current is None:
            changed.append(f'target:{name}')
            if not module.check_mode:
                targets_by_name[name] = call('iscsi.target.create', payload)
            continue
        update = wanted_fields(payload, current,
                               ('alias', 'mode', 'groups', 'auth_networks'))
        if update:
            changed.append(f'target:{name}')
            if not module.check_mode:
                call('iscsi.target.update', current['id'], update)

    associations = call('iscsi.targetextent.query')
    for desired in module.params['associations']:
        target = targets_by_name.get(desired['target'])
        extent = extents_by_name.get(desired['extent'])
        label = f'association:{desired["target"]}:{desired["extent"]}'
        if target is None or extent is None:
            if module.check_mode:
                changed.append(label)
                continue
            module.fail_json(msg=f'{label} references an unknown resource.')
        matches = [item for item in associations
                   if item['target'] == target['id'] and
                   item['extent'] == extent['id']]
        if len(matches) > 1:
            module.fail_json(msg=f'Multiple {label} resources exist.')
        if not matches:
            changed.append(label)
            if not module.check_mode:
                call('iscsi.targetextent.create', {
                    'target': target['id'], 'extent': extent['id'],
                    'lunid': desired['lunid']})
        elif matches[0].get('lunid') != desired['lunid']:
            changed.append(label)
            if not module.check_mode:
                call('iscsi.targetextent.update', matches[0]['id'],
                     {'lunid': desired['lunid']})

    module.exit_json(changed=bool(changed), changed_resources=changed)


if __name__ == '__main__':
    main()
