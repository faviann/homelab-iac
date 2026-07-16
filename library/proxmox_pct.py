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
    - "Wraps common pct operations: status, config, set, exec, reboot"
    - "Adds wait_exec: bounded polling until the container accepts a guest command through the host"
    - Every invocation carries an upper bound; an overrunning pct is killed and reported
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
        choices: ['status', 'config', 'set', 'exec', 'reboot', 'wait_exec']
    exec_command:
        description:
            - Command to execute inside the container (when command=exec)
            - Passed to C(sh -c) so shell syntax and quoting are preserved
            - Ignored by wait_exec, whose readiness probe is deliberately fixed and minimal
        required: false
        type: str
    ready_timeout:
        description:
            - Overall readiness deadline in seconds
            - Required when command=wait_exec; no default here on purpose, see the module notes
            - No further attempt starts once the deadline would be crossed
        required: false
        type: int
    ready_delay:
        description:
            - Delay between readiness attempts in seconds
            - Required when command=wait_exec
        required: false
        type: int
    ready_command_timeout:
        description:
            - Per-attempt execution timeout in seconds
            - Required when command=wait_exec
            - A readiness attempt that exceeds it is killed and counted as a failed attempt
        required: false
        type: int
    config_options:
        description:
            - Configuration options to set (when command=set)
            - Dict of key-value pairs
        required: false
        type: dict
notes:
    - The readiness bounds have no defaults here. Their single source of truth is the
      calling role's defaults/argument_specs pair, which always passes all three
      explicitly. A copy in this module would be unreachable and could only drift.
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
# require them. The probe is fixed rather than configurable so it cannot drift
# into a boot-complete or application-health check.
READY_EXEC_COMMAND = 'true'

# rc reported for an attempt killed by its per-attempt execution timeout,
# matching the conventional timeout(1) exit status.
TIMEOUT_RC = 124

# Smallest budget in which a real pct exec can plausibly answer. An attempt with
# less than this cannot report anything but its own kill, so the deadline is
# reached instead of starting one.
MIN_USEFUL_ATTEMPT_SECONDS = 1.0

# Grace for collecting output from an already-killed process. The kill releases
# the pipes at once, so this only bites if the killpg fallback left a child
# holding them; reading must never outlast the timeout it exists to enforce.
KILL_GRACE_SECONDS = 5

# Upper bound for every pct command except reboot. status, config, set and exec
# are /etc/pve reads-writes or a trivial guest command: on a healthy host they
# answer in well under a second. The realistic failure is not slowness but a
# wedged pmxcfs, where /etc/pve stops answering at all and the call never
# returns. 60s is far past any healthy latency (it absorbs a quorum re-election
# blip) while still failing a run in seconds rather than stalling it forever.
PCT_COMMAND_TIMEOUT_SECONDS = 60

# reboot is the one remaining command with a duration of its own: it shuts the
# guest down and starts it again, and pct's own shutdown timeout alone defaults
# to 60s. Bounding it at PCT_COMMAND_TIMEOUT_SECONDS would kill legitimately slow
# reboots mid-flight, so it gets its own bound with room for a slow guest to stop
# and boot. It is a bound against a wedged host, not a reboot SLA: a healthy
# reboot finishes far inside it, and readiness after the reboot is proven
# separately by wait_exec.
PCT_REBOOT_TIMEOUT_SECONDS = 300


def kill_process_group(proc):
    """Kill the timed-out pct process and every child it spawned."""
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        proc.kill()


def run_pct_command(module, cmd_args, kill_after):
    """Execute pct command and return results.

    kill_after is a mandatory wall-clock kill deadline in seconds: an overrunning
    pct process is killed and reported as a failed command rather than blocking
    the run forever. It is required rather than optional so "every pct invocation
    is bounded" is a property of this function's signature, not a convention a
    future call site can forget.
    """
    cmd = ['pct'] + cmd_args

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            # Every call is bounded, so every call must be killable, so every call
            # gets its own process group: pct spawns children (lxc-attach and the
            # guest command) that inherit the output pipes, so killing pct alone
            # would leave them holding those pipes and communicate() would block
            # exactly as long as the hang it must bound.
            #
            # Deliberate consequence: detaching means Ctrl-C no longer reaches pct.
            # Accepted. No long-running interactive pct command remains in this
            # adapter -- every command it offers is a short host operation or a
            # reboot -- so the bound above, not the operator's terminal, is what
            # ends a wedged call. Re-coupling Ctrl-C would cost the kill that
            # bounds these calls, which is the more valuable of the two.
            start_new_session=True
        )
    except Exception as e:
        module.fail_json(msg=f"Failed to execute pct command: {str(e)}")

    try:
        stdout, stderr = proc.communicate(timeout=kill_after)
        rc = proc.returncode
    except subprocess.TimeoutExpired:
        kill_process_group(proc)
        try:
            stdout, stderr = proc.communicate(timeout=KILL_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            # kill_process_group fell back to killing pct alone and a surviving
            # child still holds the pipes. Abandon the output rather than block.
            stdout, stderr = '', 'output unavailable: killed pct did not release its pipes'
        rc = TIMEOUT_RC
        stderr = (stderr or '') + (
            f"\npct command exceeded its {round(kill_after, 2)}s execution timeout and was killed"
        )
    except Exception as e:
        module.fail_json(msg=f"Failed to execute pct command: {str(e)}")

    return {
        'stdout': stdout.strip(),
        'stderr': stderr.strip(),
        'rc': rc,
        'cmd': ' '.join(cmd)
    }


def wait_for_guest_command(module, vmid, ready_timeout, ready_delay, command_timeout):
    """Poll pct exec until it succeeds or the overall readiness deadline expires.

    Attempts are separated by ready_delay and bounded by command_timeout, further
    clamped to the time left on the deadline so a hung attempt cannot overrun the
    overall budget. An attempt only starts if the deadline still leaves room for
    the delay before it and a usable budget for the attempt itself: a shorter one
    could only ever report its own kill, masking the container's real error. The
    first attempt always runs, even under a deadline smaller than that budget.
    """
    cmd_args = ['exec', str(vmid), '--', 'sh', '-c', READY_EXEC_COMMAND]
    started = time.monotonic()
    deadline = started + ready_timeout
    attempts = 0
    # The container's own answer, kept so a timed-out attempt cannot mask it.
    last_genuine = None

    while True:
        attempts += 1
        remaining = deadline - time.monotonic()
        kill_after = min(command_timeout, max(remaining, MIN_USEFUL_ATTEMPT_SECONDS))
        result = run_pct_command(module, cmd_args, kill_after=kill_after)
        if result['rc'] == 0:
            return result
        if result['rc'] != TIMEOUT_RC:
            last_genuine = result
        if time.monotonic() + ready_delay + MIN_USEFUL_ATTEMPT_SECONDS >= deadline:
            break
        time.sleep(ready_delay)

    elapsed = round(time.monotonic() - started, 2)
    if last_genuine is not None:
        diagnosis = last_genuine
        condition = (
            f"Last error rc={last_genuine['rc']}, "
            f"stderr: {last_genuine['stderr'] or '<empty>'}"
        )
    else:
        diagnosis = result
        # No figure of our own here: attempts near the deadline are killed at a
        # clamped budget, so naming command_timeout would contradict the stderr
        # below, which carries the budget the last attempt was actually killed at.
        condition = (
            "Every attempt was killed at its per-attempt execution timeout; the "
            f"container never answered. Last attempt rc={result['rc']}, "
            f"stderr: {result['stderr'] or '<empty>'}"
        )

    module.fail_json(
        msg=(
            f"LXC {vmid} did not become ready for guest commands: "
            f"'pct exec {vmid} -- sh -c {READY_EXEC_COMMAND}' never succeeded within the "
            f"{ready_timeout}s readiness deadline ({attempts} attempts over {elapsed}s). "
            f"{condition}"
        ),
        changed=False,
        vmid=vmid,
        stdout=diagnosis['stdout'],
        stderr=diagnosis['stderr'],
        rc=diagnosis['rc'],
        cmd=diagnosis['cmd'],
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
                choices=['status', 'config', 'set', 'exec', 'reboot', 'wait_exec']
            ),
            exec_command=dict(type='str', required=False),
            config_options=dict(type='dict', required=False),
            # No defaults for the readiness bounds: see the module notes. The
            # calling role owns those numbers and always passes them.
            ready_timeout=dict(type='int', required=False),
            ready_delay=dict(type='int', required=False),
            ready_command_timeout=dict(type='int', required=False)
        ),
        required_if=[
            ('command', 'wait_exec', ['ready_timeout', 'ready_delay', 'ready_command_timeout'])
        ],
        supports_check_mode=True
    )

    vmid = module.params['vmid']
    command = module.params['command']
    exec_command = module.params.get('exec_command')
    config_options = module.params.get('config_options')

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
        if module.check_mode:
            module.exit_json(
                changed=False,
                msg=f"Would wait for LXC {vmid} to accept guest commands"
            )
        result = wait_for_guest_command(
            module, vmid, ready_timeout, ready_delay, ready_command_timeout
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
    elif command == 'reboot':
        cmd_args = ['reboot', str(vmid)]
        changed = True
    else:
        module.fail_json(msg=f"Unsupported command: {command}")

    # Execute command
    if module.check_mode and changed:
        module.exit_json(changed=True, msg=f"Would execute: pct {' '.join(cmd_args)}")

    kill_after = (
        PCT_REBOOT_TIMEOUT_SECONDS if command == 'reboot' else PCT_COMMAND_TIMEOUT_SECONDS
    )
    result = run_pct_command(module, cmd_args, kill_after=kill_after)

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

    # Fail if command failed. Naming the LXC and the exact call is what makes a
    # wedged host actionable, and matches the readiness message above: a killed
    # call reports rc=TIMEOUT_RC and carries the bound it exceeded in stderr.
    if result['rc'] != 0:
        module.fail_json(
            msg=(
                f"LXC {vmid}: '{result['cmd']}' failed with rc={result['rc']}. "
                f"stderr: {result['stderr'] or '<empty>'}"
            ),
            **response
        )

    module.exit_json(**response)


if __name__ == '__main__':
    main()
