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

if (
    module.params["state"] == "started"
    or os.environ.get("LIFECYCLE_WIRING_REAL_ROLES") == "1"
) and not module.check_mode:
    state_dir = Path(os.environ["LIFECYCLE_TEST_STATE_DIR"])
    vmid = module.params["vmid"]
    events_path = state_dir / f"{vmid}.events"
    with events_path.open("a", encoding="utf-8") as events:
        if module.params["state"] == "started":
            events.write("container_transition\n")
        else:
            events.write("api_reconciliation\n")
    if module.params["state"] == "started":
        (state_dir / f"{vmid}.state").write_text("running", encoding="utf-8")

module.exit_json(changed=True)
