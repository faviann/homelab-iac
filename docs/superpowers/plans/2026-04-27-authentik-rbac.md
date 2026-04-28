# Authentik RBAC & Group Architecture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Formalise authentik group architecture with domain bundle groups, a `registration-approver` Role, and group-based access on all OIDC apps.

**Architecture:** Flat groups in three categories — domain bundles (`admins`, `media`, `reading`, `storage`) for application access, per-app groups created on demand for surgical access, and integration groups (`ldapsearch`, `PVEAdmins`) for external systems. The OIDC blueprint generator is extended to remove stale order-0 `always-allow` bindings and emit group bindings at orders 1+2. A new `15-roles.yaml` blueprint defines the `registration-approver` Role without assigning it.

**Tech Stack:** authentik 2026.02, blueprint YAML, Python 3.12 (`scripts/authentik_blueprint_sync.py`), pytest

---

## File Map

| File | Change |
|------|--------|
| `stacks/auth/auth/appdata/authentik/blueprints/10-groups.yaml` | Stop managing `content-editors`; add `storage`, `reading`; keep integration group `PVEAdmins` |
| `stacks/auth/auth/appdata/authentik/blueprints/15-roles.yaml` | **Create** — `registration-approver` role |
| `stacks/auth/auth/appdata/authentik/blueprints/40-applications.yaml` | Fix `home-wildcard`, `media-wildcard` bindings; add `ldap` binding |
| `stacks/auth/auth/appdata/authentik/blueprints/80-oidc-apps.yaml.j2` | Regenerated — stale `always-allow` bindings removed; group bindings replace them |
| `stacks/auth/auth/appdata/authentik/blueprints/90-cleanup-legacy.yaml` | **Create** — remove legacy `content-editors` group after bindings are gone |
| `stacks/auth/auth/appdata/authentik/oidc-apps.yaml` | Replace `policy: always-allow` with `group:` on each app |
| `scripts/authentik_blueprint_sync.py` | Add role and cleanup blueprint constants; update `blueprint_plan()`; extend `generate_oidc_blueprint_content()` for group bindings |
| `tests/unit/test_oidc_manifest.py` | Add tests for group binding generation and roles plan ordering |

---

## Deployment Invariants

- `reading` and `storage` are intentionally empty at deployment time. Do not add human memberships in this change.
- `admins` must retain immediate access to every gated Authentik application.
- `ldapsearch` and `PVEAdmins` are integration groups, not application domain bundles. Do not make them children of `admins`.
- `PVEAdmins` remains repo-managed because `85-proxmox-oidc.yaml.j2` references it for the Proxmox groups claim.
- This deployment creates `registration-approver` only. Do not assign the role to any user or group.
- `content-editors` is intentionally removed in this deployment. Removal must happen in a late cleanup blueprint after application bindings no longer reference it.
- Do not apply blueprints between tasks. Apply only after all tasks and final checks are complete.

---

## Task 1: Update `10-groups.yaml`

**Files:**
- Modify: `stacks/auth/auth/appdata/authentik/blueprints/10-groups.yaml`

- [ ] **Step 1: Replace file contents**

Replace the full file with:

```yaml
version: 1
metadata:
  name: repo-auth-groups
  labels:
    blueprints.goauthentik.io/instantiate: 'false'
    blueprints.goauthentik.io/description: Managed from ServerManagementScripts
entries:
- model: authentik_core.group
  state: present
  identifiers:
    name: admins
  attrs:
    name: admins
- model: authentik_core.group
  state: present
  identifiers:
    name: ldapsearch
  attrs:
    name: ldapsearch
- model: authentik_core.group
  state: present
  identifiers:
    name: media
  attrs:
    name: media
- model: authentik_core.group
  state: present
  identifiers:
    name: PVEAdmins
  attrs:
    name: PVEAdmins
- model: authentik_core.group
  state: present
  identifiers:
    name: reading
  attrs:
    name: reading
- model: authentik_core.group
  state: present
  identifiers:
    name: storage
  attrs:
    name: storage
```

- [ ] **Step 2: Commit**

```bash
git add stacks/auth/auth/appdata/authentik/blueprints/10-groups.yaml
git commit -m "feat(auth): add reading and storage groups"
```

---

## Task 2: Create `15-roles.yaml` and register in blueprint plan

**Files:**
- Create: `stacks/auth/auth/appdata/authentik/blueprints/15-roles.yaml`
- Modify: `scripts/authentik_blueprint_sync.py`
- Test: `tests/unit/test_oidc_manifest.py`

- [ ] **Step 1: Write the failing tests**

Add this class to `tests/unit/test_oidc_manifest.py` after `OidcBlueprintPlanTests`:

```python
class RolesBlueprintPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_script()

    def test_roles_blueprint_in_plan(self):
        plan = self.mod.blueprint_plan([])
        names = [name for name, _ in plan]
        self.assertIn("repo-auth-roles", names)

    def test_roles_blueprint_path_in_plan(self):
        plan = self.mod.blueprint_plan([])
        paths = [path for _, path in plan]
        self.assertIn("15-roles.yaml", paths)

    def test_roles_blueprint_after_groups_in_plan(self):
        plan = self.mod.blueprint_plan([])
        names = [name for name, _ in plan]
        self.assertLess(names.index("repo-auth-groups"), names.index("repo-auth-roles"))

    def test_roles_blueprint_before_flows_in_plan(self):
        plan = self.mod.blueprint_plan(["default-authentication-flow"])
        names = [name for name, _ in plan]
        self.assertLess(
            names.index("repo-auth-roles"),
            names.index("repo-auth-flow-default-authentication-flow"),
        )
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
python -m pytest tests/unit/test_oidc_manifest.py::RolesBlueprintPlanTests -v
```

Expected: 4 failures — `repo-auth-roles` not found in plan.

- [ ] **Step 3: Create `15-roles.yaml`**

Create only the role. Do not assign it to any user or group in this deployment.

```yaml
version: 1
metadata:
  name: repo-auth-roles
  labels:
    blueprints.goauthentik.io/instantiate: 'false'
    blueprints.goauthentik.io/description: Managed from ServerManagementScripts
entries:
- model: authentik_rbac.role
  state: present
  identifiers:
    name: registration-approver
  attrs:
    name: registration-approver
    permissions:
    - authentik_core.view_user
    - authentik_core.change_user
```

- [ ] **Step 4: Add role blueprint constants to `scripts/authentik_blueprint_sync.py`**

After line `GROUPS_FILE = BLUEPRINT_ROOT / "10-groups.yaml"`, add:

```python
ROLES_FILE = BLUEPRINT_ROOT / "15-roles.yaml"
ROLES_BLUEPRINT_INSTANCE_NAME = "repo-auth-roles"
ROLES_BLUEPRINT_DEPLOYED_NAME = str(ROLES_FILE.relative_to(BLUEPRINT_ROOT))
```

- [ ] **Step 5: Update `blueprint_plan()` in `scripts/authentik_blueprint_sync.py`**

Find this block (around line 800):
```python
def blueprint_plan(flow_slugs: list[str]) -> list[tuple[str, str]]:
    steps = [("repo-auth-groups", "10-groups.yaml")]
```

Replace with:
```python
def blueprint_plan(flow_slugs: list[str]) -> list[tuple[str, str]]:
    steps = [
        ("repo-auth-groups", "10-groups.yaml"),
        (ROLES_BLUEPRINT_INSTANCE_NAME, ROLES_BLUEPRINT_DEPLOYED_NAME),
    ]
```

- [ ] **Step 6: Run tests to confirm they pass**

```bash
python -m pytest tests/unit/test_oidc_manifest.py::RolesBlueprintPlanTests -v
```

Expected: 4 passed.

- [ ] **Step 7: Run full test suite to check for regressions**

```bash
python -m pytest tests/unit/test_oidc_manifest.py -v
```

Expected: all 38 passed.

- [ ] **Step 8: Commit**

```bash
git add stacks/auth/auth/appdata/authentik/blueprints/15-roles.yaml \
        scripts/authentik_blueprint_sync.py \
        tests/unit/test_oidc_manifest.py
git commit -m "feat(auth): add registration-approver role blueprint"
```

---

## Task 3: Update `40-applications.yaml`

**Files:**
- Modify: `stacks/auth/auth/appdata/authentik/blueprints/40-applications.yaml`

- [ ] **Step 1: Normalize `home-wildcard` bindings**

Find the `home-wildcard` binding at order 0 that references `content-editors`. Replace it with an absent tombstone that does not reference the old group:

```yaml
- model: authentik_policies.policybinding
  state: absent
  identifiers:
    target: !KeyOf 'app-home-wildcard'
    order: 0
```

Find the existing `home-wildcard` order 1 binding. It currently points at `admins`. Change only the group reference to `storage`, leaving the binding present at order 1:

```yaml
    group: !Find [authentik_core.group, [name, storage]]
```

After that order 1 binding, add `admins` at order 2:

```yaml
- model: authentik_policies.policybinding
  state: present
  identifiers:
    target: !KeyOf 'app-home-wildcard'
    order: 2
  attrs:
    target: !KeyOf 'app-home-wildcard'
    order: 2
    enabled: true
    negate: false
    failure_result: false
    timeout: 30
    group: !Find [authentik_core.group, [name, admins]]
```

- [ ] **Step 2: Normalize `media-wildcard` bindings**

Find the `media-wildcard` order 0 binding that points at `media`. Replace it with an absent tombstone:

```yaml
- model: authentik_policies.policybinding
  state: absent
  identifiers:
    target: !KeyOf 'app-media-wildcard'
    order: 0
```

Find the existing `media-wildcard` order 1 binding. It currently points at `admins`. Change only the group reference to `media`:

```yaml
    group: !Find [authentik_core.group, [name, media]]
```

Find the existing `media-wildcard` order 2 binding that references `content-editors`. Keep it present at order 2 and change the group reference to `admins`:

```yaml
- model: authentik_policies.policybinding
  state: present
  identifiers:
    target: !KeyOf 'app-media-wildcard'
    order: 2
  attrs:
    target: !KeyOf 'app-media-wildcard'
    order: 2
    enabled: true
    negate: false
    failure_result: false
    timeout: 30
    group: !Find [authentik_core.group, [name, admins]]
```

- [ ] **Step 3: Add `ldapsearch` binding to `ldap` app**

After the `app-ldap` application entry, add:

```yaml
- model: authentik_policies.policybinding
  state: present
  identifiers:
    target: !KeyOf 'app-ldap'
    order: 0
  attrs:
    target: !KeyOf 'app-ldap'
    order: 0
    enabled: true
    negate: false
    failure_result: false
    timeout: 30
    group: !Find [authentik_core.group, [name, ldapsearch]]
```

- [ ] **Step 4: Verify `content-editors` is no longer actively referenced**

Run:

```bash
rg "content-editors" stacks/auth/auth/appdata/authentik/blueprints/40-applications.yaml
```

Expected: no matches.

- [ ] **Step 5: Commit**

```bash
git add stacks/auth/auth/appdata/authentik/blueprints/40-applications.yaml
git commit -m "feat(auth): normalize application group bindings"
```

---

## Task 4: Extend blueprint generator for group bindings

**Files:**
- Modify: `scripts/authentik_blueprint_sync.py`
- Test: `tests/unit/test_oidc_manifest.py`

- [ ] **Step 1: Write the failing tests**

Add this class to `tests/unit/test_oidc_manifest.py` after `RolesBlueprintPlanTests`:

```python
class OidcGroupBindingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_script()

    def test_group_binding_emits_domain_group(self):
        content = self.mod.generate_oidc_blueprint_content([minimal_app(group="media")])
        self.assertIn("name, media", content)

    def test_group_binding_emits_admins_group(self):
        content = self.mod.generate_oidc_blueprint_content([minimal_app(group="media")])
        self.assertIn("name, admins", content)

    def test_group_binding_uses_orders_1_and_2(self):
        content = self.mod.generate_oidc_blueprint_content([minimal_app(group="media")])
        self.assertIn("order: 1", content)
        self.assertIn("order: 2", content)

    def test_group_binding_does_not_emit_expression_policy(self):
        content = self.mod.generate_oidc_blueprint_content([minimal_app(group="media")])
        self.assertNotIn("expressionpolicy", content)

    def test_group_binding_emits_order_0_absent_tombstone(self):
        content = self.mod.generate_oidc_blueprint_content([minimal_app(group="media")])
        self.assertIn("  state: absent\n  identifiers:\n    target: !KeyOf app-test-app\n    order: 0", content)

    def test_policy_binding_still_uses_order_0(self):
        content = self.mod.generate_oidc_blueprint_content([minimal_app(policy="always-allow")])
        self.assertIn("order: 0", content)
        self.assertNotIn("order: 1", content)
        self.assertNotIn("order: 2", content)

    def test_reading_group_binding(self):
        content = self.mod.generate_oidc_blueprint_content([minimal_app(group="reading")])
        self.assertIn("name, reading", content)
        self.assertIn("name, admins", content)
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
python -m pytest tests/unit/test_oidc_manifest.py::OidcGroupBindingTests -v
```

Expected: 6 failures and 1 pass. The policy fallback test may already pass before implementation.

- [ ] **Step 3: Update `generate_oidc_blueprint_content()` in `scripts/authentik_blueprint_sync.py`**

Find this line (around line 187):
```python
        policy = app.get("policy", "always-allow")
```

Replace with:
```python
        group = app.get("group")
        policy = app.get("policy", "always-allow")
```

Then find the tail of the existing `lines += [...]` block (lines 247–262 — this is the
end of the same list that also contains the application definition above it):
```python
            "",
            "- model: authentik_policies.policybinding",
            "  state: present",
            "  identifiers:",
            f"    target: !KeyOf {app_id}",
            "    order: 0",
            "  attrs:",
            f"    target: !KeyOf {app_id}",
            "    order: 0",
            "    enabled: true",
            "    negate: false",
            "    failure_result: false",
            "    timeout: 30",
            f"    policy: !Find [authentik_policies_expression.expressionpolicy, [name, {policy}]]",
            "",
        ]
```

Replace with (closes the existing list at the separator, then branches on `group`):
```python
            "",
        ]
        if group:
            lines += [
                "- model: authentik_policies.policybinding",
                "  state: absent",
                "  identifiers:",
                f"    target: !KeyOf {app_id}",
                "    order: 0",
                "",
                "- model: authentik_policies.policybinding",
                "  state: present",
                "  identifiers:",
                f"    target: !KeyOf {app_id}",
                "    order: 1",
                "  attrs:",
                f"    target: !KeyOf {app_id}",
                "    order: 1",
                "    enabled: true",
                "    negate: false",
                "    failure_result: false",
                "    timeout: 30",
                f"    group: !Find [authentik_core.group, [name, {group}]]",
                "",
                "- model: authentik_policies.policybinding",
                "  state: present",
                "  identifiers:",
                f"    target: !KeyOf {app_id}",
                "    order: 2",
                "  attrs:",
                f"    target: !KeyOf {app_id}",
                "    order: 2",
                "    enabled: true",
                "    negate: false",
                "    failure_result: false",
                "    timeout: 30",
                "    group: !Find [authentik_core.group, [name, admins]]",
                "",
            ]
        else:
            lines += [
                "- model: authentik_policies.policybinding",
                "  state: present",
                "  identifiers:",
                f"    target: !KeyOf {app_id}",
                "    order: 0",
                "  attrs:",
                f"    target: !KeyOf {app_id}",
                "    order: 0",
                "    enabled: true",
                "    negate: false",
                "    failure_result: false",
                "    timeout: 30",
                f"    policy: !Find [authentik_policies_expression.expressionpolicy, [name, {policy}]]",
                "",
            ]
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
python -m pytest tests/unit/test_oidc_manifest.py::OidcGroupBindingTests -v
```

Expected: 7 passed.

- [ ] **Step 5: Run full test suite to check for regressions**

```bash
python -m pytest tests/unit/test_oidc_manifest.py -v
```

Expected: all 45 passed.

- [ ] **Step 6: Commit**

```bash
git add scripts/authentik_blueprint_sync.py tests/unit/test_oidc_manifest.py
git commit -m "feat(auth): extend OIDC blueprint generator to support group bindings"
```

---

## Task 5: Update manifest and regenerate blueprint

**Files:**
- Modify: `stacks/auth/auth/appdata/authentik/oidc-apps.yaml`
- Modify (generated): `stacks/auth/auth/appdata/authentik/blueprints/80-oidc-apps.yaml.j2`
- Test: `tests/unit/test_oidc_manifest.py`

- [ ] **Step 1: Write failing and drift-detection tests**

Add these tests to `OidcBlueprintGenerationTests` in `tests/unit/test_oidc_manifest.py`:

```python
def test_real_manifest_uses_group_bindings_not_always_allow(self):
    apps = self.mod.load_oidc_manifest()
    content = self.mod.generate_oidc_blueprint_content(apps)
    self.assertNotIn("name, always-allow", content)
    self.assertIn("name, admins", content)

def test_committed_oidc_blueprint_matches_generator(self):
    apps = self.mod.load_oidc_manifest()
    expected = self.mod.generate_oidc_blueprint_content(apps)
    actual = self.mod.OIDC_BLUEPRINT_FILE.read_text(encoding="utf-8")
    self.assertEqual(actual, expected)
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
python -m pytest tests/unit/test_oidc_manifest.py::OidcBlueprintGenerationTests::test_real_manifest_uses_group_bindings_not_always_allow -v
```

Expected: FAIL — `always-allow` still present in generated content.

- [ ] **Step 3: Update `oidc-apps.yaml`**

Replace the `policy: always-allow` field on each app with the appropriate `group:` field:

```yaml
apps:
  - name: RomM
    slug: romm-public
    provider_name: romm-public-oidc
    launch_url: https://romm.public.faviann.com
    client_id: romm-public
    client_secret_var: stack_vars.romm_oidc_client_secret
    signing_certificate_var: stack_vars.romm_oidc_signing_certificate_name
    redirect_uris:
      - https://romm.public.faviann.com/api/oauth/openid
    custom_scope_mappings:
      - name: RomM Email Verification
        scope_name: email
        description: Ensures RomM receives a verified email claim
        expression: |-
          return {
              "email": user.email,
              "email_verified": True,
          }
    group: media
    sub_mode: user_email
    issuer_mode: global

  - name: Audiobookshelf
    slug: audiobookshelf-public
    provider_name: audiobookshelf-public-oidc
    launch_url: https://audiobookshelf.public.faviann.com
    client_id: audiobookshelf-public
    client_secret_var: stack_vars.audiobookshelf_oidc_client_secret
    signing_certificate_var: stack_vars.public_oidc_signing_certificate_name
    redirect_uris:
      - https://audiobookshelf.public.faviann.com/auth/openid/callback
      - https://audiobookshelf.public.faviann.com/auth/openid/mobile-redirect
    custom_scope_mappings:
      - name: Reading Apps Email Verification
        scope_name: email
        expression: |-
          return {
              "email": user.email,
              "email_verified": True,
          }
    group: reading
    sub_mode: user_email
    issuer_mode: global

  - name: Komga
    slug: komga-public
    provider_name: komga-public-oidc
    launch_url: https://komga.public.faviann.com
    client_id: komga-public
    client_secret_var: stack_vars.komga_oidc_client_secret
    signing_certificate_var: stack_vars.public_oidc_signing_certificate_name
    redirect_uris:
      - https://komga.public.faviann.com/login/oauth2/code/authentik
    custom_scope_mappings:
      - name: Reading Apps Email Verification
        scope_name: email
        expression: |-
          return {
              "email": user.email,
              "email_verified": True,
          }
    group: reading
    sub_mode: user_email
    issuer_mode: global

  - name: Calibre-Web Automated
    slug: calibre-web-automated-public
    provider_name: calibre-web-automated-public-oidc
    launch_url: https://calibre-web-automated.public.faviann.com
    client_id: calibre-web-automated-public
    client_secret_var: stack_vars.calibre_web_automated_oidc_client_secret
    signing_certificate_var: stack_vars.public_oidc_signing_certificate_name
    redirect_uris:
      - https://calibre-web-automated.public.faviann.com/login/generic/authorized
    custom_scope_mappings:
      - name: Reading Apps Email Verification
        scope_name: email
        expression: |-
          return {
              "email": user.email,
              "email_verified": True,
          }
    group: reading
    sub_mode: user_email
    issuer_mode: global

  - name: ReadMeABook
    slug: readmeabook-public
    provider_name: readmeabook-public-oidc
    launch_url: https://readmeabook.public.faviann.com
    client_id: readmeabook-public
    client_secret_var: stack_vars.readmeabook_oidc_client_secret
    signing_certificate_var: stack_vars.public_oidc_signing_certificate_name
    redirect_uris:
      - https://readmeabook.public.faviann.com/api/auth/oidc/callback
    custom_scope_mappings:
      - name: Reading Apps Email Verification
        scope_name: email
        expression: |-
          return {
              "email": user.email,
              "email_verified": True,
          }
    group: reading
    sub_mode: user_email
    issuer_mode: global
```

- [ ] **Step 4: Run test to confirm it passes**

```bash
python -m pytest tests/unit/test_oidc_manifest.py::OidcBlueprintGenerationTests::test_real_manifest_uses_group_bindings_not_always_allow -v
```

Expected: PASS.

- [ ] **Step 5: Run drift-detection test to confirm the committed blueprint is stale**

```bash
python -m pytest tests/unit/test_oidc_manifest.py::OidcBlueprintGenerationTests::test_committed_oidc_blueprint_matches_generator -v
```

Expected: FAIL — `80-oidc-apps.yaml.j2` has not been regenerated yet.

- [ ] **Step 6: Regenerate `80-oidc-apps.yaml.j2`**

```bash
python -c "
import sys
sys.path.insert(0, 'scripts')
import authentik_blueprint_sync as bps
path = bps.generate_oidc_blueprint_file()
print(f'Generated: {path}')
"
```

Expected output: `Generated: .../80-oidc-apps.yaml.j2`

- [ ] **Step 7: Run drift-detection test again**

```bash
python -m pytest tests/unit/test_oidc_manifest.py::OidcBlueprintGenerationTests::test_committed_oidc_blueprint_matches_generator -v
```

Expected: PASS.

- [ ] **Step 8: Run full test suite**

```bash
python -m pytest tests/unit/test_oidc_manifest.py -v
```

Expected: all 47 passed.

- [ ] **Step 9: Verify generated blueprint contains group references, not always-allow**

```bash
grep -E "name, (media|reading|admins|always-allow)" \
  stacks/auth/auth/appdata/authentik/blueprints/80-oidc-apps.yaml.j2
```

Expected: lines with `media`, `reading`, `admins` — no `always-allow`.

- [ ] **Step 10: Commit**

```bash
git add stacks/auth/auth/appdata/authentik/oidc-apps.yaml \
        stacks/auth/auth/appdata/authentik/blueprints/80-oidc-apps.yaml.j2 \
        tests/unit/test_oidc_manifest.py
git commit -m "feat(auth): gate OIDC apps on reading/media groups via blueprint generator"
```

---

## Task 6: Remove legacy `content-editors` after binding migration

**Files:**
- Create: `stacks/auth/auth/appdata/authentik/blueprints/90-cleanup-legacy.yaml`
- Modify: `scripts/authentik_blueprint_sync.py`
- Test: `tests/unit/test_oidc_manifest.py`

- [ ] **Step 1: Write the failing tests**

Add this class to `tests/unit/test_oidc_manifest.py` after `OidcGroupBindingTests`:

```python
class LegacyCleanupBlueprintPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_script()

    def test_legacy_cleanup_blueprint_in_plan(self):
        plan = self.mod.blueprint_plan([])
        names = [name for name, _ in plan]
        self.assertIn("repo-auth-legacy-cleanup", names)

    def test_legacy_cleanup_blueprint_path_in_plan(self):
        plan = self.mod.blueprint_plan([])
        paths = [path for _, path in plan]
        self.assertIn("90-cleanup-legacy.yaml", paths)

    def test_legacy_cleanup_runs_after_applications_and_oidc(self):
        plan = self.mod.blueprint_plan([])
        names = [name for name, _ in plan]
        self.assertGreater(
            names.index("repo-auth-legacy-cleanup"),
            names.index("repo-auth-applications"),
        )
        self.assertGreater(
            names.index("repo-auth-legacy-cleanup"),
            names.index("repo-auth-oidc-apps"),
        )
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
python -m pytest tests/unit/test_oidc_manifest.py::LegacyCleanupBlueprintPlanTests -v
```

Expected: 3 failures — `repo-auth-legacy-cleanup` is not in the plan.

- [ ] **Step 3: Create `90-cleanup-legacy.yaml`**

```yaml
version: 1
metadata:
  name: repo-auth-legacy-cleanup
  labels:
    blueprints.goauthentik.io/instantiate: 'false'
    blueprints.goauthentik.io/description: Managed from ServerManagementScripts
entries:
- model: authentik_core.group
  state: absent
  identifiers:
    name: content-editors
```

- [ ] **Step 4: Add legacy cleanup constants to `scripts/authentik_blueprint_sync.py`**

After the role blueprint constants, add:

```python
LEGACY_CLEANUP_FILE = BLUEPRINT_ROOT / "90-cleanup-legacy.yaml"
LEGACY_CLEANUP_BLUEPRINT_INSTANCE_NAME = "repo-auth-legacy-cleanup"
LEGACY_CLEANUP_BLUEPRINT_DEPLOYED_NAME = str(LEGACY_CLEANUP_FILE.relative_to(BLUEPRINT_ROOT))
```

- [ ] **Step 5: Append cleanup to the end of `blueprint_plan()`**

Find the final `steps.extend([...])` block in `blueprint_plan()`. After that block and before `return steps`, add:

```python
    steps.append((LEGACY_CLEANUP_BLUEPRINT_INSTANCE_NAME, LEGACY_CLEANUP_BLUEPRINT_DEPLOYED_NAME))
```

The cleanup blueprint must run after `repo-auth-applications` and `repo-auth-oidc-apps`.

- [ ] **Step 6: Run tests to confirm they pass**

```bash
python -m pytest tests/unit/test_oidc_manifest.py::LegacyCleanupBlueprintPlanTests -v
```

Expected: 3 passed.

- [ ] **Step 7: Run full test suite**

```bash
python -m pytest tests/unit/test_oidc_manifest.py -v
```

Expected: all 50 passed.

- [ ] **Step 8: Commit**

```bash
git add stacks/auth/auth/appdata/authentik/blueprints/90-cleanup-legacy.yaml \
        scripts/authentik_blueprint_sync.py \
        tests/unit/test_oidc_manifest.py
git commit -m "feat(auth): remove legacy content-editors group after migration"
```

---

## Final Check

- [ ] **Run all unit tests one last time**

```bash
python -m pytest tests/unit/ -v
```

Expected: all tests pass with no failures.

- [ ] **Verify legacy group references are gone from active blueprints**

```bash
rg "content-editors" stacks/auth/auth/appdata/authentik/blueprints
```

Expected: the only match is the `state: absent` tombstone in `90-cleanup-legacy.yaml`.

- [ ] **Verify Proxmox integration group remains managed**

```bash
rg "PVEAdmins" stacks/auth/auth/appdata/authentik/blueprints/10-groups.yaml \
  stacks/auth/auth/appdata/authentik/blueprints/85-proxmox-oidc.yaml.j2
```

Expected: matches in both files.
