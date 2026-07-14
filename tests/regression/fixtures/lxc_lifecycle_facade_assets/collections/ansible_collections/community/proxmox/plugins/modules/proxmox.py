#!/usr/bin/python
"""Minimal Proxmox module double for lifecycle facade regressions."""

from ansible.module_utils.basic import AnsibleModule


module = AnsibleModule(
    argument_spec={
        "node": {"type": "str"},
        "vmid": {"type": "int"},
        "state": {"type": "str"},
    },
    supports_check_mode=True,
)
module.exit_json(changed=True)
