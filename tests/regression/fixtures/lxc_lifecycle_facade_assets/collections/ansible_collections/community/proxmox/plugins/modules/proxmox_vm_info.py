#!/usr/bin/python
"""Fixture Proxmox observation adapter for lifecycle regressions."""

import json
import ssl
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

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

if not module.params["api_host"]:
    module.exit_json(changed=False, proxmox_vms=[])

base_url = (
    f"https://{module.params['api_host']}:{module.params['api_port']}/api2/json"
)
authorization = (
    f"PVEAPIToken={module.params['api_user']}!{module.params['api_token_id']}="
    f"{module.params['api_token_secret']}"
)
ssl_context = ssl.create_default_context()
if not module.params["validate_certs"]:
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE


def request_data(path):
    request = Request(
        f"{base_url}{path}",
        headers={"Authorization": authorization},
    )
    with urlopen(request, context=ssl_context, timeout=10) as response:
        return json.load(response)["data"]


try:
    request_data("/version")
    resources = request_data("/cluster/resources?type=vm")
    nodes = sorted(
        {
            item["node"]
            for item in resources
            if item.get("type") == "lxc" and item.get("node")
        }
    )
    containers = []
    for node in nodes:
        node_containers = request_data(f"/nodes/{quote(node, safe='')}/lxc")
        containers.extend({**item, "node": node} for item in node_containers)
except (HTTPError, URLError, OSError, KeyError, TypeError, ValueError) as error:
    module.fail_json(msg=f"Controlled Proxmox observation failed: {error}")

module.exit_json(changed=False, proxmox_vms=containers)
