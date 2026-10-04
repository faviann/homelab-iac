#!/usr/bin/python
"""Minimal Proxmox module double for lifecycle facade regressions."""

import os
from pathlib import Path

from ansible.module_utils.basic import AnsibleModule


module = AnsibleModule(
    argument_spec={
        "api_host": {"type": "str"},
        "api_port": {"type": "int"},
        "api_user": {"type": "str"},
        "api_token_id": {"type": "str"},
        "api_token_secret": {"type": "str", "no_log": True},
        "validate_certs": {"type": "bool"},
        "node": {"type": "str"},
        "vmid": {"type": "int"},
        "hostname": {"type": "str"},
        "ostemplate": {"type": "str"},
        "pool": {"type": "str"},
        "password": {"type": "str", "no_log": True},
        "pubkey": {"type": "str"},
        "description": {"type": "str"},
        "storage": {"type": "str"},
        "disk": {"type": "raw"},
        "mount_volumes": {"type": "raw"},
        "cores": {"type": "int"},
        "cpus": {"type": "int"},
        "cpuunits": {"type": "int"},
        "memory": {"type": "int"},
        "swap": {"type": "int"},
        "netif": {"type": "dict"},
        "unprivileged": {"type": "bool"},
        "onboot": {"type": "bool"},
        "timezone": {"type": "str"},
        "nameserver": {"type": "str"},
        "searchdomain": {"type": "str"},
        "mounts": {"type": "raw"},
        "startup": {"type": "str"},
        "tags": {"type": "str"},
        "timeout": {"type": "int"},
        "ostype": {"type": "str"},
        "update": {"type": "bool"},
        "state": {"type": "str"},
    },
    supports_check_mode=True,
)

REAL_ROLES = os.environ.get("LIFECYCLE_WIRING_REAL_ROLES") == "1"
RUNTIME_TRANSITIONS = {"started": "running", "stopped": "stopped"}

if (module.params["state"] in RUNTIME_TRANSITIONS or REAL_ROLES) and not module.check_mode:
    state_dir = Path(os.environ["LIFECYCLE_TEST_STATE_DIR"])
    vmid = module.params["vmid"]
    if module.params["state"] == "started":
        event = "container_transition"
    elif REAL_ROLES:
        event = "api_reconciliation"
    else:
        event = None
    if event:
        with (state_dir / f"{vmid}.events").open("a", encoding="utf-8") as events:
            events.write(f"{event}\n")
    if module.params["state"] in RUNTIME_TRANSITIONS:
        (state_dir / f"{vmid}.state").write_text(
            RUNTIME_TRANSITIONS[module.params["state"]], encoding="utf-8"
        )

module.exit_json(changed=True)
