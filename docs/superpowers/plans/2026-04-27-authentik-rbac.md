# Authentik RBAC & Group Architecture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Formalise authentik group architecture with domain bundle groups, a `registration-approver` Role, and group-based access on all OIDC apps.

**Architecture:** Flat groups in two tiers — domain bundles (`admins`, `media`, `reading`, `storage`) for automatic bundle access, and per-app groups created on demand for surgical access. The OIDC blueprint generator is extended to emit group bindings (orders 1+2) in addition to the existing expression-policy binding (order 0). A new `15-roles.yaml` blueprint defines the `registration-approver` Role.

**Tech Stack:** authentik 2026.02, blueprint YAML, Python 3.12 (`scripts/authentik_blueprint_sync.py`), pytest

---

## File Map

| File | Change |
|------|--------|
| `stacks/auth/auth/appdata/authentik/blueprints/10-groups.yaml` | Remove `content-editors`; add `storage`, `reading` |
| `stacks/auth/auth/appdata/authentik/blueprints/15-roles.yaml` | **Create** — `registration-approver` role |
| `stacks/auth/auth/appdata/authentik/blueprints/40-applications.yaml` | Fix `home-wildcard`, `media-wildcard` bindings; add `ldap` binding |
| `stacks/auth/auth/appdata/authentik/blueprints/80-oidc-apps.yaml.j2` | Regenerated — group bindings replace `always-allow` |
| `stacks/auth/auth/appdata/authentik/oidc-apps.yaml` | Replace `policy: always-allow` with `group:` on each app |
| `scripts/authentik_blueprint_sync.py` | Add `ROLES_FILE` constant; update `blueprint_plan()`; extend `generate_oidc_blueprint_content()` for group bindings |
| `tests/unit/test_oidc_manifest.py` | Add tests for group binding generation and roles plan ordering |

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
  state: absent
  identifiers:
    name: content-editors
  attrs:
    name: content-editors
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
git commit -m "feat(auth): add reading/storage groups, retire content-editors"
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

- [ ] **Step 4: Add `ROLES_FILE` constant to `scripts/authentik_blueprint_sync.py`**

After line `GROUPS_FILE = BLUEPRINT_ROOT / "10-groups.yaml"`, add:

```python
ROLES_FILE = BLUEPRINT_ROOT / "15-roles.yaml"
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
        ("repo-auth-roles", "15-roles.yaml"),
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

Expected: all 37 passed.

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

- [ ] **Step 1: Fix `home-wildcard` binding**

Find the `home-wildcard` policy binding that references `content-editors` (order 0). The blueprint engine matches bindings by `(target, order)`, so updating the `group` attr in-place is enough — no absent+present dance needed.

Change:
```yaml
    group: !Find [authentik_core.group, [name, content-editors]]
```
To:
```yaml
    group: !Find [authentik_core.group, [name, storage]]
```

Leave `state: present` and all other fields unchanged.

- [ ] **Step 2: Fix `media-wildcard` binding**

Find the `media-wildcard` policy binding that references `content-editors` (order 2):

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
    group: !Find [authentik_core.group, [name, content-editors]]
```

Replace `state: present` with `state: absent`:

```yaml
- model: authentik_policies.policybinding
  state: absent
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
    group: !Find [authentik_core.group, [name, content-editors]]
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

- [ ] **Step 4: Commit**

```bash
git add stacks/auth/auth/appdata/authentik/blueprints/40-applications.yaml
git commit -m "feat(auth): migrate application bindings to storage group; gate ldap app"
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

    def test_group_binding_does_not_use_order_0(self):
        content = self.mod.generate_oidc_blueprint_content([minimal_app(group="media")])
        self.assertNotIn("order: 0", content)

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

Expected: 7 failures.

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

Then find this block (around lines 244-258):
```python
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

Replace with:
```python
            if group:
                lines += [
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

Expected: all 44 passed.

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

- [ ] **Step 1: Write failing test**

Add this test to `OidcBlueprintGenerationTests` in `tests/unit/test_oidc_manifest.py`:

```python
def test_real_manifest_uses_group_bindings_not_always_allow(self):
    apps = self.mod.load_oidc_manifest()
    content = self.mod.generate_oidc_blueprint_content(apps)
    self.assertNotIn("name, always-allow", content)
    self.assertIn("name, admins", content)
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

- [ ] **Step 5: Run full test suite**

```bash
python -m pytest tests/unit/test_oidc_manifest.py -v
```

Expected: all 45 passed.

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

- [ ] **Step 7: Verify generated blueprint contains group references, not always-allow**

```bash
grep -E "name, (media|reading|admins|always-allow)" \
  stacks/auth/auth/appdata/authentik/blueprints/80-oidc-apps.yaml.j2
```

Expected: lines with `media`, `reading`, `admins` — no `always-allow`.

- [ ] **Step 8: Commit**

```bash
git add stacks/auth/auth/appdata/authentik/oidc-apps.yaml \
        stacks/auth/auth/appdata/authentik/blueprints/80-oidc-apps.yaml.j2 \
        tests/unit/test_oidc_manifest.py
git commit -m "feat(auth): gate OIDC apps on reading/media groups via blueprint generator"
```

---

## Final Check

- [ ] **Run all unit tests one last time**

```bash
python -m pytest tests/unit/ -v
```

Expected: all tests pass with no failures.
