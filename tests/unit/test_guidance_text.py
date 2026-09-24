"""Keep tracked guidance from teaching superseded command forms.

docs/command-policy.md records the superseded forms, the scanned surfaces, and
the text-check allowlist this check reads.
"""

from __future__ import annotations

from collections.abc import Iterator
import fnmatch
from pathlib import Path
import re
import subprocess

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
POLICY = "docs/command-policy.md"

_TOOL = r"(?:ansible-playbook|ansible-lint|pytest)"
SUPERSEDED_FORMS = {
    "--tags validation, provision, or bootstrap": r"--tags[ =](?:validation|provision|bootstrap)\b",
    "ansible-playbook, ansible-lint, or pytest run directly": (
        rf"\buv run(?:[ \t]+--?[\w-]+)*[ \t]+{_TOOL}\b"
        rf"|(?:(?<![\w./-])|(?<=bin/)){_TOOL}[ \t]+(?:-\S|\S*[/.]\S*)"
        rf"|^[ \t]*{_TOOL}[ \t]*$"
    ),
    "ansible -m ping": r"\bansible\b[^`\n]*[ \t]-m[ \t]+ping\b",
    "ansible-inventory --host, --list, or --graph": r"\bansible-inventory\b[^`\n]*--(?:host|list|graph)\b",
    "ansible-vault encrypt, edit, or view": r"\bansible-vault[ \t]+(?:encrypt|edit|view)\b",
    "the lifecycle regression runner": r"\b(?:python3?|uv run)\b[^`\n]*run_lxc_lifecycle_regressions\.py",
    "python -m pytest or unittest, or a test file run with python": (
        r"\bpython3?[ \t]+(?:-m[ \t]+(?:pytest|unittest)\b|\S*test_\w*\.py)"
    ),
    "python -m stack_update_policy validate": r"\bpython3?[ \t]+(?:-\S+[ \t]+)*-m[ \t]+stack_update_policy\b",
    'python -c "import proxmoxer, requests"': r"\bimport proxmoxer\b",
    "./configure-vault.sh": r"\bconfigure-vault\.sh\b",
    "./rotate-vault-passphrase.sh": r"\brotate-vault-passphrase\.sh\b",
    "./setup.sh bootstrap": r"\bsetup\.sh[ \t]+bootstrap\b",
    "ansible-galaxy collection or role install or list": (
        r"\bansible-galaxy[ \t]+(?:collection|role)[ \t]+(?:install|list)\b"
    ),
}
SUPERSEDED_PATTERNS = {
    form: re.compile(pattern, re.MULTILINE) for form, pattern in SUPERSEDED_FORMS.items()
}
RUN_INVOCATION = re.compile(r"\./run\.sh\b([^`|;&>#\n]*)")
EARLY_ANSIBLE_OPTION = re.compile(r"-e|--extra-vars|--tags")
SHELL_OUTPUT = re.compile(r"\b(?:echo|printf)\b(.*)")
SHELL_STRING = re.compile(r"'([^']*)'|\"((?:[^\"\\]|\\.)*)\"")
YAML_COMMENT = re.compile(r"(?:^|\s)#(.*)$", re.MULTILINE)


def offenses(text: str) -> list[str]:
    text = text.replace("\\\n", " ")
    found = [
        f"{form}: {match.group(0).strip()!r}"
        for form, pattern in SUPERSEDED_PATTERNS.items()
        for match in pattern.finditer(text)
    ]
    for invocation in RUN_INVOCATION.finditer(text):
        words = invocation.group(1).split()
        before_separator = words[: words.index("--")] if "--" in words else words
        if any(EARLY_ANSIBLE_OPTION.match(word) for word in before_separator):
            found.append(
                f"-e or --tags before -- in ./run.sh: {invocation.group(0).strip()!r}"
            )
    return found


def yaml_message_strings(node: object, in_message: bool = False) -> Iterator[str]:
    if isinstance(node, dict):
        for key, value in node.items():
            is_message = isinstance(key, str) and (key == "msg" or key.endswith("_msg"))
            yield from yaml_message_strings(value, in_message or is_message)
    elif isinstance(node, list):
        for item in node:
            yield from yaml_message_strings(item, in_message)
    elif in_message and isinstance(node, str):
        yield node


def guidance_text(path: str, source: str) -> str | None:
    if path.endswith(".md") and not path.startswith("tests/"):
        return source
    if path in ("inventory/vault.yml.example", ".ansible-lint"):
        return source
    if path == "site.yml" or (
        path.startswith("playbooks/") and path.endswith((".yml", ".yaml"))
    ):
        comments = [match.group(1) for match in YAML_COMMENT.finditer(source)]
        messages = [
            message
            for document in yaml.safe_load_all(source)
            for message in yaml_message_strings(document)
        ]
        return "\n".join(comments + messages)
    if path.endswith(".sh"):
        strings = [
            single or double
            for line in source.replace("\\\n", " ").splitlines()
            for output in SHELL_OUTPUT.finditer(line)
            for single, double in SHELL_STRING.findall(output.group(1))
        ]
        return "\n".join(strings)
    return None


def allowlisted_globs() -> list[str]:
    policy = (REPO_ROOT / POLICY).read_text(encoding="utf-8")
    section = policy.split("### Text-check allowlist", 1)[1].split("\n## ", 1)[0]
    return re.findall(r"^\| `([^`]+)` \|", section, re.MULTILINE)


@pytest.mark.parametrize(
    "text",
    [
        "./run.sh --limit servarr -e stack_filter=beets-flask",
        "./run.sh -e proxmox_skip_self=false --limit workstation",
        "Run ./run.sh --tags provision to provision only.",
        "./run.sh --limit auth \\\n  --extra-vars foo=bar",
        "Use `--tags validation` to test connectivity",
        "uv run ansible-playbook playbooks/lab-connectivity.yml",
        "`uv run --frozen ansible-playbook` runs against live hosts",
        ".venv/bin/ansible-playbook bootstrap.yml",
        "`.venv/bin/pytest --version`",
        "# Repo-wide lint gate: `uv run --locked ansible-lint` must exit 0.",
        "ansible-lint\n",
        "`pytest tests/unit -x`",
        "ansible all -m ping",
        "`ansible-inventory --host auth`",
        "uv run --locked ansible-vault view inventory/vault.yml",
        "uv run --locked python tests/regression/run_lxc_lifecycle_regressions.py --full",
        "python -m unittest discover",
        "python tests/unit/test_vault_token.py",
        "uv run --locked python -B -m stack_update_policy validate stacks/x",
        'uv run --locked python -c "import proxmoxer, requests"',
        "./configure-vault.sh",
        "./rotate-vault-passphrase.sh",
        "./setup.sh bootstrap",
        "# Install with: ansible-galaxy role install -r requirements/roles.yml",
    ],
)
def test_superseded_form_is_reported(text: str) -> None:
    assert offenses(text)


@pytest.mark.parametrize(
    "text",
    [
        "./run.sh --limit auth -- -e foo=bar --tags docker",
        "./run.sh --limit servarr --stack beets-flask > /tmp/deploy.log 2>&1",
        "`./run.sh --include-controller` | Manage the control node -e",
        "Do not invoke Ansible, `uv`, or `pytest` directly.",
        "pytest owns the `test_*.py` files under `tests/`",
        "The unit suite is collected by pytest\nfrom the test tree.",
        "Authentik blueprints use tags that ansible-lint cannot parse.",
        "# ansible-vault encrypted file: must start with the $ANSIBLE_VAULT header",
        "The wrapper forwards arguments after `--` to `ansible-playbook`.",
        "`--tags` and `-e` only after `--`",
    ],
)
def test_prose_about_a_tool_is_not_reported(text: str) -> None:
    assert offenses(text) == []


def test_shell_scope_is_output_literals_not_execution() -> None:
    text = guidance_text(
        "script.sh",
        "uv run --locked ansible-lint\n"
        "echo \"Try './run.sh -e stack_filter=x'\" >&2\n",
    )

    assert text is not None
    assert [finding.split(":")[0] for finding in offenses(text)] == [
        "-e or --tags before -- in ./run.sh"
    ]


def test_yaml_scope_is_comments_and_messages_not_tasks() -> None:
    text = guidance_text(
        "playbooks/example.yml",
        "- name: Example\n"
        "  ansible.builtin.command: ansible-galaxy collection install x\n"
        "  # Deploy with ./run.sh --tags docker\n"
        "- ansible.builtin.fail:\n"
        "    msg: >-\n"
        "      Run ansible-vault edit\n"
        "      inventory/vault.yml\n",
    )

    assert text is not None
    assert sorted(finding.split(":")[0] for finding in offenses(text)) == [
        "-e or --tags before -- in ./run.sh",
        "ansible-vault encrypt, edit, or view",
    ]


def test_tracked_guidance_teaches_no_superseded_form() -> None:
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    allowed = allowlisted_globs()
    findings = [
        f"{path}: {finding}"
        for path in tracked
        if not any(fnmatch.fnmatch(path, glob) for glob in allowed)
        and (
            text := guidance_text(
                path, (REPO_ROOT / path).read_text(encoding="utf-8")
            )
        )
        is not None
        for finding in offenses(text)
    ]

    assert not findings, (
        f"tracked guidance teaches a superseded form; use the replacement in {POLICY}:\n"
        + "\n".join(findings)
    )
