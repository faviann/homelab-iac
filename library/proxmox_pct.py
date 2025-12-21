#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2025, ServerManagementScripts
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function
__metaclass__ = type

DOCUMENTATION = r'''
---
module: proxmox_pct
short_description: Manage Proxmox LXC containers via pct command
description:
    - Execute pct commands against Proxmox LXC containers
    - Wraps common pct operations: status, config, set, exec, start, stop, restart
version_added: "1.0.0"
author:
    - "ServerManagementScripts"
options:
    vmid:
        description:
            - The unique container ID
        required: true
        type: int
    command:
        description:
            - The pct command to execute
        required: true
        type: str
        choices: ['status', 'config', 'set', 'exec', 'start', 'stop', 'restart', 'shutdown']
    exec_command:
        description:
            - Command to execute inside the container (when command=exec)
        required: false
        type: str
    config_options:
        description:
            - Configuration options to set (when command=set)
            - Dict of key-value pairs
        required: false
        type: dict
    timeout:
        description:
            - Timeout for stop/shutdown commands in seconds
        required: false
        type: int
        default: 30
'''

EXAMPLES = r'''
- name: Check container status
  proxmox_pct:
    vmid: 100
    command: status

- name: Get container configuration
  proxmox_pct:
    vmid: 100
    command: config

- name: Set container options
  proxmox_pct:
    vmid: 100
    command: set
    config_options:
      memory: 2048
      cores: 2

- name: Execute command in container
  proxmox_pct:
    vmid: 100
    command: exec
    exec_command: "ls -la /root"

- name: Start container
  proxmox_pct:
    vmid: 100
    command: start

- name: Stop container
  proxmox_pct:
    vmid: 100
    command: stop

- name: Restart container
  proxmox_pct:
    vmid: 100
    command: restart
'''

RETURN = r'''
stdout:
    description: Standard output from pct command
    returned: always
    type: str
stderr:
    description: Standard error from pct command
    returned: always
    type: str
rc:
    description: Return code from pct command
    returned: always
    type: int
status:
    description: Parsed container status (when command=status)
    returned: when command=status
    type: str
config:
    description: Parsed container configuration (when command=config)
    returned: when command=config
    type: dict
changed:
    description: Whether the operation changed the container state
    returned: always
    type: bool
'''

from ansible.module_utils.basic import AnsibleModule
import subprocess
import re


def run_pct_command(module, cmd_args):
    """Execute pct command and return results"""
    cmd = ['pct'] + cmd_args
    
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True
        )
        stdout, stderr = proc.communicate()
        rc = proc.returncode
        
        return {
            'stdout': stdout.strip(),
            'stderr': stderr.strip(),
            'rc': rc,
            'cmd': ' '.join(cmd)
        }
    except Exception as e:
        module.fail_json(msg=f"Failed to execute pct command: {str(e)}")


def parse_status(stdout):
    """Parse pct status output to extract state"""
    # pct status output format: "status: running"
    match = re.search(r'status:\s*(\w+)', stdout)
    if match:
        return match.group(1)
    return stdout.strip()


def parse_config(stdout):
    """Parse pct config output into dict"""
    config = {}
    for line in stdout.split('\n'):
        if ':' in line:
            key, value = line.split(':', 1)
            config[key.strip()] = value.strip()
    return config


def main():
    module = AnsibleModule(
        argument_spec=dict(
            vmid=dict(type='int', required=True),
            command=dict(
                type='str',
                required=True,
                choices=['status', 'config', 'set', 'exec', 'start', 'stop', 'restart', 'shutdown']
            ),
            exec_command=dict(type='str', required=False),
            config_options=dict(type='dict', required=False),
            timeout=dict(type='int', required=False, default=30)
        ),
        supports_check_mode=True
    )

    vmid = module.params['vmid']
    command = module.params['command']
    exec_command = module.params.get('exec_command')
    config_options = module.params.get('config_options')
    timeout = module.params['timeout']

    # Build pct command arguments
    if command == 'status':
        cmd_args = ['status', str(vmid)]
        changed = False
    elif command == 'config':
        cmd_args = ['config', str(vmid)]
        changed = False
    elif command == 'set':
        if not config_options:
            module.fail_json(msg="config_options required for 'set' command")
        cmd_args = ['set', str(vmid)]
        for key, value in config_options.items():
            cmd_args.extend([f'--{key}', str(value)])
        changed = True
    elif command == 'exec':
        if not exec_command:
            module.fail_json(msg="exec_command required for 'exec' command")
        cmd_args = ['exec', str(vmid), '--'] + exec_command.split()
        changed = False
    elif command == 'start':
        cmd_args = ['start', str(vmid)]
        changed = True
    elif command == 'stop':
        cmd_args = ['stop', str(vmid), '--timeout', str(timeout)]
        changed = True
    elif command == 'restart':
        cmd_args = ['restart', str(vmid), '--timeout', str(timeout)]
        changed = True
    elif command == 'shutdown':
        cmd_args = ['shutdown', str(vmid), '--timeout', str(timeout)]
        changed = True
    else:
        module.fail_json(msg=f"Unsupported command: {command}")

    # Execute command
    if module.check_mode and changed:
        module.exit_json(changed=True, msg=f"Would execute: pct {' '.join(cmd_args)}")

    result = run_pct_command(module, cmd_args)

    # Build response
    response = {
        'changed': changed,
        'stdout': result['stdout'],
        'stderr': result['stderr'],
        'rc': result['rc'],
        'cmd': result['cmd']
    }

    # Parse command-specific output
    if command == 'status' and result['rc'] == 0:
        response['status'] = parse_status(result['stdout'])
    elif command == 'config' and result['rc'] == 0:
        response['config'] = parse_config(result['stdout'])

    # Fail if command failed
    if result['rc'] != 0:
        module.fail_json(
            msg=f"pct command failed: {result['stderr']}",
            **response
        )

    module.exit_json(**response)


if __name__ == '__main__':
    main()
