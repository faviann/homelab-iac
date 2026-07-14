#!/usr/bin/python
"""Minimal Proxmox module double for lifecycle facade regressions."""

import os
from pathlib import Path

from ansible.module_utils.basic import AnsibleModule


module = AnsibleModule(
    argument_spec={
        "node": {"type": "str"},
        "vmid": {"type": "int"},
        "state": {"type": "str"},
    },
    supports_check_mode=True,
)

if module.params["state"] == "started" and not module.check_mode:
    state_dir = Path(os.environ["LIFECYCLE_TEST_STATE_DIR"])
    vmid = module.params["vmid"]
    events_path = state_dir / f"{vmid}.events"
    with events_path.open("a", encoding="utf-8") as events:
        events.write("container_transition\n")
    (state_dir / f"{vmid}.state").write_text("running", encoding="utf-8")

module.exit_json(changed=True)
