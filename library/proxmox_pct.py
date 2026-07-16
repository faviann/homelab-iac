#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2025, homelab-iac
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function
__metaclass__ = type

DOCUMENTATION = r'''
---
module: proxmox_pct
short_description: Manage Proxmox LXC containers via pct command
description:
    - Execute pct commands against Proxmox LXC containers
    - "Wraps common pct operations: status, config, set, exec, start, stop, restart, reboot, shutdown"
    - "Adds wait_exec: bounded polling until the container accepts a guest command through the host"
version_added: "1.0.0"
author:
    - "homelab-iac"
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
        choices: ['status', 'config', 'set', 'exec', 'start', 'stop', 'restart', 'reboot', 'shutdown', 'wait_exec']
    exec_command:
        description:
            - Command to execute inside the container (when command=exec)
            - Passed to C(sh -c) so shell syntax and quoting are preserved
            - "When command=wait_exec this is the readiness probe; it defaults to a minimal true command"
        required: false
        type: str
    ready_timeout:
        description:
            - Overall readiness deadline in seconds (when command=wait_exec)
            - No further attempt starts once the deadline would be crossed
        required: false
        type: int
        default: 120
    ready_delay:
        description:
            - Delay between readiness attempts in seconds (when command=wait_exec)
        required: false
        type: int
        default: 3
    ready_command_timeout:
        description:
            - Per-attempt execution timeout in seconds (when command=wait_exec)
            - A readiness attempt that exceeds it is killed and counted as a failed attempt
        required: false
        type: int
        default: 10
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

- name: Reboot container
    proxmox_pct:
        vmid: 100
        command: reboot

- name: Wait for a restarted container to accept guest commands
  proxmox_pct:
    vmid: 100
    command: wait_exec
    ready_timeout: 120
    ready_delay: 3
    ready_command_timeout: 10
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
attempts:
    description: Number of readiness attempts made (when command=wait_exec)
    returned: when command=wait_exec
    type: int
elapsed:
    description: Seconds spent polling for readiness (when command=wait_exec)
    returned: when command=wait_exec
    type: float
'''

from ansible.module_utils.basic import AnsibleModule
import os
import signal
import subprocess
import re
import time


# Readiness at this seam means only that the container accepts a guest command
# through the Proxmox host. It deliberately says nothing about SSH access,
# systemd boot state, or application health: those belong to the modules that
# require them.
READY_EXEC_COMMAND = 'true'

# rc reported for an attempt killed by its per-attempt execution timeout,
# matching the conventional timeout(1) exit status.
TIMEOUT_RC = 124

# Floor for a clamped per-attempt timeout, so a nearly exhausted deadline still
# gives the final attempt a chance to run rather than a zero-length one.
MIN_ATTEMPT_TIMEOUT = 0.1


def kill_process_group(proc):
    """Kill the timed-out pct process and every child it spawned."""
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        proc.kill()


def run_pct_command(module, cmd_args, timeout=None):
    """Execute pct command and return results.

    timeout is a real per-invocation execution timeout in seconds. When it is
    None the call waits indefinitely, preserving the behaviour of every
    non-readiness pct command (pct stop/shutdown govern their own duration via
    pct's --timeout). When it is set, an overrunning pct process is killed and
    reported as a failed attempt rather than blocking the run forever.
    """
    cmd = ['pct'] + cmd_args

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            # Own process group: pct spawns children (lxc-attach and the guest
            # command itself) that inherit the output pipes. Killing only pct
            # would leave them holding those pipes open, and the timeout would
            # then block in communicate() exactly as long as the hang it exists
            # to bound. The whole group must go.
            start_new_session=True
        )
    except Exception as e:
        module.fail_json(msg=f"Failed to execute pct command: {str(e)}")

    try:
        stdout, stderr = proc.communicate(timeout=timeout)
        rc = proc.returncode
    except subprocess.TimeoutExpired:
        kill_process_group(proc)
        stdout, stderr = proc.communicate()
        rc = TIMEOUT_RC
        stderr = (stderr or '') + (
            f"\npct command exceeded its {round(timeout, 2)}s execution timeout and was killed"
        )
    except Exception as e:
        module.fail_json(msg=f"Failed to execute pct command: {str(e)}")

    return {
        'stdout': stdout.strip(),
        'stderr': stderr.strip(),
        'rc': rc,
        'cmd': ' '.join(cmd)
    }


def wait_for_guest_command(module, vmid, exec_command, ready_timeout, ready_delay, command_timeout):
    """Poll pct exec until it succeeds or the overall readiness deadline expires.

    Every attempt is bounded by command_timeout, attempts are separated by
    ready_delay, and no new attempt starts once ready_timeout would be crossed.
    The per-attempt timeout is additionally clamped to the time left on the
    deadline, so a hung final attempt cannot overrun the overall budget.
    """
    cmd_args = ['exec', str(vmid), '--', 'sh', '-c', exec_command]
    started = time.monotonic()
    deadline = started + ready_timeout
    attempts = 0

    while True:
        attempts += 1
        attempt_timeout = max(
            MIN_ATTEMPT_TIMEOUT,
            min(command_timeout, deadline - time.monotonic()),
        )
        result = run_pct_command(module, cmd_args, timeout=attempt_timeout)
        if result['rc'] == 0:
            result['attempts'] = attempts
            result['elapsed'] = round(time.monotonic() - started, 2)
            return result
        if time.monotonic() + ready_delay >= deadline:
            break
        time.sleep(ready_delay)

    elapsed = round(time.monotonic() - started, 2)
    module.fail_json(
        msg=(
            f"LXC {vmid} did not become ready for guest commands: "
            f"'pct exec {vmid} -- sh -c {exec_command}' never succeeded within the "
            f"{ready_timeout}s readiness deadline ({attempts} attempts over {elapsed}s). "
            f"Last attempt rc={result['rc']}, stderr: {result['stderr'] or '<empty>'}"
        ),
        changed=False,
        vmid=vmid,
        attempts=attempts,
        elapsed=elapsed,
        stdout=result['stdout'],
        stderr=result['stderr'],
        rc=result['rc'],
        cmd=result['cmd'],
    )


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
                choices=[
                    'status', 'config', 'set', 'exec', 'start', 'stop',
                    'restart', 'reboot', 'shutdown', 'wait_exec'
                ]
            ),
            exec_command=dict(type='str', required=False),
            config_options=dict(type='dict', required=False),
            timeout=dict(type='int', required=False, default=30),
            ready_timeout=dict(type='int', required=False, default=120),
            ready_delay=dict(type='int', required=False, default=3),
            ready_command_timeout=dict(type='int', required=False, default=10)
        ),
        supports_check_mode=True
    )

    vmid = module.params['vmid']
    command = module.params['command']
    exec_command = module.params.get('exec_command')
    config_options = module.params.get('config_options')
    timeout = module.params['timeout']

    if command == 'wait_exec':
        ready_timeout = module.params['ready_timeout']
        ready_delay = module.params['ready_delay']
        ready_command_timeout = module.params['ready_command_timeout']
        if ready_timeout <= 0 or ready_command_timeout <= 0 or ready_delay < 0:
            module.fail_json(
                msg=(
                    "wait_exec requires ready_timeout > 0, ready_command_timeout > 0 "
                    "and ready_delay >= 0"
                )
            )
        probe_command = exec_command or READY_EXEC_COMMAND
        if module.check_mode:
            module.exit_json(
                changed=False,
                msg=f"Would wait for LXC {vmid} to accept guest commands"
            )
        result = wait_for_guest_command(
            module, vmid, probe_command, ready_timeout, ready_delay, ready_command_timeout
        )
        module.exit_json(changed=False, **result)

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
        cmd_args = ['exec', str(vmid), '--', 'sh', '-c', exec_command]
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
    elif command == 'reboot':
        cmd_args = ['reboot', str(vmid)]
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
