#!/usr/bin/python
"""Minimal parseable Proxmox observation double for facade regressions."""

from ansible.module_utils.basic import AnsibleModule


module = AnsibleModule(argument_spec={"type": {"type": "str"}}, supports_check_mode=True)
module.exit_json(changed=False, proxmox_vms=[])
