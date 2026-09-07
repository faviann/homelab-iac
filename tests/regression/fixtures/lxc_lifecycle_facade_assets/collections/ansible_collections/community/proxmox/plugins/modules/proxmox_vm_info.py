#!/usr/bin/python
"""Fixture Proxmox observation adapter for lifecycle regressions."""

import json
import os
from pathlib import Path

from ansible.module_utils.basic import AnsibleModule


module = AnsibleModule(
    argument_spec={
        "api_host": {"type": "str"},
        "api_port": {"type": "int", "default": 8006},
        "api_user": {"type": "str"},
        "api_token_id": {"type": "str"},
        "api_token_secret": {"type": "str", "no_log": True},
        "validate_certs": {"type": "bool", "default": True},
        "node": {"type": "str"},
        "type": {"type": "str"},
    },
    supports_check_mode=True,
)

fixture_path = os.environ.get("LIFECYCLE_PROXMOX_OBSERVATION")
if not fixture_path:
    module.exit_json(changed=False, proxmox_vms=[])

path = Path(fixture_path)
fixture = json.loads(path.read_text(encoding="utf-8"))
if "expected_arguments" in fixture and module.params != fixture["expected_arguments"]:
    module.fail_json(msg="Proxmox observation module arguments did not match the fixture contract")
with path.with_suffix(".calls").open("a", encoding="utf-8") as calls:
    calls.write(json.dumps({"check_mode": module.check_mode}) + "\n")
if fixture.get("fail", False):
    module.fail_json(msg="Controlled Proxmox observation failure")
module.exit_json(changed=False, proxmox_vms=fixture["proxmox_vms"])
