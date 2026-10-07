# Do SOPS, Infisical, or ansible-pull change the bootstrap node spec?

Research for [#519](https://github.com/faviann/homelab-iac/issues/519), part of map [#518](https://github.com/faviann/homelab-iac/issues/518). Broader adoption is deferred in [#517](https://github.com/faviann/homelab-iac/issues/517).

## Question

The bootstrap node spec, as decided in #518:

- **Root secrets.** chezmoi renders the vault passphrase (`~/.ansible/vault-pass`) and the fleet SSH key (`~/.ansible/ssh/proxmox_lxc`) from Bitwarden after one human unlock. Ansible never delivers them.
- **Code.** An HTTPS `git fetch` of a pushed ref from the public repository, then `./run.sh --limit workstation`.

Would adopting SOPS (with age), Infisical, or ansible-pull change either part now?

## Answer

None of the three changes the spec now. Each one either replaces the file that chezmoi renders or wraps the same fetch-and-run step. None removes the need for a root secret on the bootstrap node, and none needs anything the spec does not already provide. Adopting any of them later is a fleet-wide change that applies to both control nodes equally. That decision belongs in #517.

| Tool | Verdict |
| --- | --- |
| SOPS + age | Orthogonal. The root secret changes from a vault passphrase to an age identity. chezmoi delivers it the same way. |
| Infisical | Orthogonal now, and worse for this node if adopted. The root secret changes to a machine identity's client secret, and a restore would then depend on an Infisical server. |
| ansible-pull | Orthogonal. It is `git clone` plus `ansible-playbook -c local -l <this host>`. Pointed at the workstation, it duplicates `git fetch` plus `./run.sh` and skips the repository's guards. |

## SOPS with age

**What it would replace.** SOPS encrypts YAML values and leaves the keys readable ([community.sops guide](https://docs.ansible.com/ansible/latest/collections/community/sops/docsite/guide.html): "you can easily see which files contain which variable, but the variables themselves are encrypted"). The `community.sops.sops` vars plugin decrypts `*.sops.yaml` files in `group_vars/` and `host_vars/`. It requires "a binary executable `sops`" on the controller ([sops vars plugin](https://docs.ansible.com/ansible/latest/collections/community/sops/sops_vars.html)). Lookups, filters, and the vars plugin all need "SOPS installed on localhost" ([guide](https://docs.ansible.com/ansible/latest/collections/community/sops/docsite/guide.html)).

**What it still needs on the control node.** An age private key. SOPS reads it from `$XDG_CONFIG_HOME/sops/age/keys.txt`, falling back to `$HOME/.config/sops/age/keys.txt`. `SOPS_AGE_KEY_FILE`, `SOPS_AGE_KEY`, or `SOPS_AGE_KEY_CMD` override that path ([SOPS age docs](https://getsops.io/docs/usage/identities/age/)). The vars plugin passes its `age_keyfile` option (`ANSIBLE_SOPS_AGE_KEYFILE`) through as `SOPS_AGE_KEY_FILE` ([sops vars plugin](https://docs.ansible.com/ansible/latest/collections/community/sops/sops_vars.html)).

**Notable detail.** SOPS accepts `ssh-ed25519` and `ssh-rsa` public keys as age recipients. It finds the matching private key through `SOPS_AGE_SSH_PRIVATE_KEY_FILE`, then `SOPS_AGE_SSH_PRIVATE_KEY_CMD`, then `~/.ssh/id_ed25519`, then `~/.ssh/id_rsa`. The private key must not be password-protected ([SOPS age docs](https://getsops.io/docs/usage/identities/age/)). The fleet public key `~/.ansible/ssh/proxmox_lxc.pub` is `ssh-ed25519`. SOPS could therefore encrypt to the fleet key, and the bootstrap node would need one root secret instead of two. This is an option for #517. It does not block the spec.

**Verdict: orthogonal.** chezmoi would render an age identity instead of `~/.ansible/vault-pass`, or render nothing extra if the fleet key doubles as the age identity. The delivery mechanism, the one-time Bitwarden unlock, and the rule that Ansible never delivers root secrets all stay the same. The migration (re-encrypting `inventory/vault.yml` and replacing `./vault.sh`) is fleet-wide. It changes the workstation exactly as much as the bootstrap node.

## Infisical

**What it would replace.** The `infisical.vault` collection's `read_secrets` lookup reads secrets at run time. "Lookup plugins run on the Ansible controller during playbook parsing." The collection needs the `infisicalsdk` Python package, which `ansible-galaxy` does not install ([Infisical Ansible docs](https://infisical.com/docs/integrations/platforms/ansible)).

**What it still needs on the control node.** A machine identity's Client ID and Client Secret, passed as `INFISICAL_UNIVERSAL_AUTH_CLIENT_ID` and `INFISICAL_UNIVERSAL_AUTH_CLIENT_SECRET` ([Infisical Ansible docs](https://infisical.com/docs/integrations/platforms/ansible)). Infisical describes them as "akin to a username and password". The default Client Secret TTL of `0` never expires ([Universal Auth](https://infisical.com/docs/documentation/platform/identities/universal-auth)). Infisical gives no storage guidance beyond "Deploy your workload with the Client Secret and Client ID".

**What it adds.** A server to reach on every run. Self-hosted deployments bundle "Infisical, PostgreSQL, and Redis" ([self-hosting overview](https://infisical.com/docs/self-hosting/overview)). Self-hosted on this fleet, it would be one more LXC or stack that must be up before the bootstrap node can restore the workstation.

**Verdict: orthogonal now.** chezmoi would render a client secret instead of a vault passphrase, through the same delivery path. If adopted, it works against the bootstrap node's purpose: restoring a dead workstation would also require a live Infisical server. #517 should treat this as a cost.

## ansible-pull

**What it is.** From [`lib/ansible/cli/pull.py`](https://github.com/ansible/ansible/blob/bf2610eb39b066994bb457f95359907aef0ae972/lib/ansible/cli/pull.py):

- It checks out the repository with the `git` module (`DEFAULT_REPO_TYPE = 'git'`, `-U` URL, `-C` ref).
- It then runs `ansible-playbook` with `base_opts = '-c local '`, which is hard-coded and does not come from the `-c` option.
- Without `-l`, it limits the run to `localhost,<fqdn>,<hostname>,127.0.0.1`: the machine it runs on.
- Without a playbook argument, it picks `<fqdn>.yml`, then `<shorthostname>.yml`, then `local.yml`.
- It forwards `--vault-password-file` and `--vault-id` unchanged.
- `-o/--only-if-changed` skips the run when the checkout reports no change.

The [ansible-pull docs](https://docs.ansible.com/ansible/latest/cli/ansible-pull.html) describe its purpose as running "on each managed node, each set to run via cron", which inverts push into pull.

**Fit against the spec.**

- *Code delivery.* The checkout is the same anonymous HTTPS fetch of a ref that the spec already uses.
- *Secret delivery.* It still consumes the vault passphrase file, so nothing changes.
- *Default target.* By default it applies a playbook to the machine it runs on. On the bootstrap node, that target is `bootstrap`, not `workstation`. On the workstation, it is the self-deploy flaw that #518 exists to remove.
- *Targeting the workstation.* Reaching the workstation needs `-i inventory/hosts.yml -l workstation` and `site.yml`, plus a way around the hard-coded `-c local`. The result is a raw `ansible-playbook` invocation, which [docs/command-policy.md](../command-policy.md) supersedes with "the operation that runs it". It skips everything `./run.sh` provides: the machine-local lifecycle lock, live dependency reconciliation, named operations, and the controller-skip guard.
- *Its only distinct feature is triggering:* `-o` and cron. The spec has decided on-demand runs, and scheduled deploys are explicitly deferred to #517.

**Verdict: orthogonal.** It wraps the same fetch and run as the spec, adds no capability the spec needs, and bypasses `./run.sh`. If #517 ever wants scheduled deploys, the smaller lever is a timer on the bootstrap node that runs `git fetch` and then `./run.sh --limit workstation`, not ansible-pull.

## Sources

- SOPS age identities: <https://getsops.io/docs/usage/identities/age/>
- community.sops guide: <https://docs.ansible.com/ansible/latest/collections/community/sops/docsite/guide.html>
- community.sops vars plugin: <https://docs.ansible.com/ansible/latest/collections/community/sops/sops_vars.html>
- Infisical Ansible collection: <https://infisical.com/docs/integrations/platforms/ansible>
- Infisical Universal Auth: <https://infisical.com/docs/documentation/platform/identities/universal-auth>
- Infisical self-hosting overview: <https://infisical.com/docs/self-hosting/overview>
- ansible-pull CLI docs: <https://docs.ansible.com/ansible/latest/cli/ansible-pull.html>
- ansible-pull source at `bf2610eb`: <https://github.com/ansible/ansible/blob/bf2610eb39b066994bb457f95359907aef0ae972/lib/ansible/cli/pull.py>
