# OpenClaw on Workstation LXC — Design Spec

**Date:** 2026-05-08
**Status:** Approved

## Context

The workstation LXC already runs several AI agent tools (Claude Code, Codex, Hermes) managed via Home Manager and the `nix-openclaw`-style flake pattern. OpenClaw is an AI gateway platform that exposes a WebSocket gateway on port 18789, manages messaging channels, and supports plugins and memory systems. It needs to:

- Run persistently as a systemd user service (no manual login to start)
- Survive LXC rebuilds (state, credentials, sessions must persist)
- Be installed and managed the same way as Hermes — via a first-party flake input wired into Home Manager

## Approach

Use the official [`nix-openclaw`](https://github.com/openclaw/nix-openclaw) Home Manager module, added as a flake input alongside the existing `hermes-agent` input. The module handles binary installation, `OPENCLAW_NIX_MODE=1`, and systemd service declaration. The `~/.openclaw` directory is added to the Ansible persistent home bind mounts so all gateway state (credentials, sessions, memory, generated config) survives LXC rebuilds.

Gateway auth token is **not** declared in the Nix config. OpenClaw auto-generates it on first `openclaw onboard` run and writes it to `~/.openclaw`. The persistent mount means onboarding runs once, ever.

## Files Changed

### `ServerManagementScripts` repo

**`playbooks/roles/config/lxc_workstation_baseline/defaults/main.yml`**
- Add `~/.openclaw` to `workstation_persistent_home_links`, same pattern as `.hermes`, `.claude`, `.codex`

**`playbooks/roles/config/lxc_workstation_baseline/templates/workstation-setup.sh.j2`**
- Add `openclaw` to the binary validation list
- Add `openclaw gateway status` as a non-fatal health check (gateway may not be onboarded on first run)

### `~/repos/dotfiles` repo

**`flake.nix`**
- Add input: `nix-openclaw.url = "github:openclaw/nix-openclaw";`
- Pass module to `homeConfigurations.workstation`:
  ```nix
  modules = [
    inputs.nix-openclaw.homeManagerModules.openclaw
    ./home/workstation.nix
  ];
  ```

**`home/workstation.nix`**
- Add `programs.openclaw` block:
  ```nix
  programs.openclaw = {
    enable = true;
    stateDir = "~/.openclaw";
    systemd.enable = true;
    systemd.unitName = "openclaw-gateway";
  };
  ```
- Override the module's default `WantedBy` target (it targets `graphical-session.target`; the headless LXC has no graphical session):
  ```nix
  systemd.user.services.openclaw-gateway = {
    Install.WantedBy = lib.mkForce [ "default.target" ];
  };
  ```
  This matches the pattern used by `hermes-gateway` and `aoe-serve`.

## Post-Setup Flow

1. `uv run --locked ansible-playbook site.yml --limit workstation` — Ansible adds `~/.openclaw` persistent mount
2. User SSHes in → `workstation-setup` prompts → `home-manager switch` installs openclaw and starts `openclaw-gateway.service` via `sd-switch`
3. User runs `openclaw onboard` once to configure API key and generate gateway auth token → written to `~/.openclaw`
4. From this point, the service auto-starts on reboot and persists across LXC rebuilds

## Verification

```bash
# Binary present
openclaw --version

# Service running
systemctl --user status openclaw-gateway

# Gateway healthy
openclaw gateway status
openclaw doctor
```

## Out of Scope

- Traefik routing to the openclaw dashboard (port 18789) — can be added later
- Channel setup (Telegram, Discord, etc.) — user configures post-install
- Plugin configuration — user configures post-install
