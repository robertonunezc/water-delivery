# Cubic Template UI Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate the shared Django UI shell to the Cubic Admin scaffold while preserving existing project JavaScript and current `pg-*` page behavior.

**Architecture:** Add a minimal Cubic vendor asset layer under `core/static/core/vendor/cubic/`, then migrate the authenticated base shell and login shell to Cubic markup. Keep `core/css/design-system.css` and `core/js/design-system.js` in place so existing page templates keep working while the shell adopts Cubic.

**Tech Stack:** Django 5.2 templates/staticfiles, Bootstrap 3.3.7, jQuery 2.1.4, Cubic Admin CSS/JS, existing vanilla `pg-*` design-system behavior.

**Spec:** `docs/superpowers/specs/2026-10-08-cubic-template-ui-migration-design.md`

## Global Constraints

- Keep all existing project JavaScript files unchanged, including `core/static/core/js/design-system.js` and app JS under `orders/static`, `clients/static`, `routes/static`, and `invoice/static`.
- Do not edit existing inline page scripts.
- Copy only the required Cubic static assets; do not copy sample HTML pages, documentation, unused plugins, source maps, `.DS_Store`, package metadata, or Grunt files.
- Load Cubic CSS before `core/css/design-system.css`; load `core/css/cubic-overrides.css` last.
- Load Cubic JS in dependency order before `core/js/design-system.js`.
- Preserve current Django URLs, view behavior, form submissions, Spanish/Mexico business copy, and CSRF-protected logout.
- Preserve Font Awesome 6 CDN loading because existing templates use `fas` classes.
- Do not put `data-toggle` and `data-pg-toggle` on the same element.
- Keep `tenant_client/templates/tenant_client/base_tenant.html` unchanged in this first migration.
- The first implementation stops after assets, authenticated base shell, login shell, tests, and verification; no full page-by-page rewrite.

## Review Focus

- Missing Cubic font/image paths can silently break icons or the login background; Task 1 asset tests pin representative files and Task 4 runs `collectstatic --dry-run`.
- Incorrect JS order can break Cubic shell controls or existing `pg-*` controls; Task 2 tests pin script order.
- Mixed `data-toggle` and `data-pg-toggle` can double-bind interactions; Task 1 includes a repository-wide template guard.
- Existing `fas` icons can disappear if Font Awesome 6 is removed; Task 2 tests require the existing CDN link until icon migration happens later.
- Login can accidentally inherit the authenticated sidebar or lose auth fields; Task 3 tests require a separate auth base and preserve username, password, CSRF, and `next`.

---

## File Structure

- Modify `core/tests.py`: add filesystem template/static guard tests.
- Create `core/static/core/vendor/cubic/`: copied minimal Cubic vendor assets.
- Create `core/static/core/css/cubic-overrides.css`: PuriGest shell tweaks scoped to Cubic layout.
- Modify `core/templates/base.html`: authenticated Cubic shell.
- Create `core/templates/base_auth.html`: Cubic auth shell without sidebar.
- Modify `core/templates/registration/login.html`: Cubic login form content.

## Task 1: Cubic Static Asset Layer And Guards

**Files:**
- Modify: `core/tests.py`
- Create: `core/static/core/vendor/cubic/bootstrap/dist/css/bootstrap.min.css`
- Create: `core/static/core/vendor/cubic/bootstrap/dist/js/bootstrap.min.js`
- Create: `core/static/core/vendor/cubic/bootstrap/dist/fonts/*`
- Create: `core/static/core/vendor/cubic/css/style.css`
- Create: `core/static/core/vendor/cubic/css/spinners.css`
- Create: `core/static/core/vendor/cubic/css/animate.css`
- Create: `core/static/core/vendor/cubic/css/colors/default.css`
- Create: `core/static/core/vendor/cubic/js/custom.js`
- Create: `core/static/core/vendor/cubic/js/sidebarmenu.js`
- Create: `core/static/core/vendor/cubic/js/jquery.slimscroll.js`
- Create: `core/static/core/vendor/cubic/js/waves.js`
- Create: `core/static/core/vendor/cubic/plugins/components/jquery/dist/jquery.min.js`
- Create: `core/static/core/vendor/cubic/plugins/images/favicon.png`
- Create: `core/static/core/vendor/cubic/plugins/images/login-register.jpg`
- Create: `core/static/core/vendor/cubic/less/icons/*/fonts/*`
- Create: `core/static/core/vendor/cubic/less/icons/material-design-iconic-font/css/materialdesignicons.min.css`
- Create: `core/static/core/css/cubic-overrides.css`

**Interfaces:**
- Produces: stable static asset paths under `core/vendor/cubic/...` for templates.
- Produces: `core/css/cubic-overrides.css` loaded after Cubic and existing design-system CSS.

- [ ] **Step 1: Write failing static/template guard tests in `core/tests.py`**

Add `CubicStaticAssetTests(SimpleTestCase)`:

```python
class CubicStaticAssetTests(SimpleTestCase):
    required_assets = [
        "core/vendor/cubic/bootstrap/dist/css/bootstrap.min.css",
        "core/vendor/cubic/bootstrap/dist/js/bootstrap.min.js",
        "core/vendor/cubic/bootstrap/dist/fonts/glyphicons-halflings-regular.woff2",
        "core/vendor/cubic/css/style.css",
        "core/vendor/cubic/css/spinners.css",
        "core/vendor/cubic/css/animate.css",
        "core/vendor/cubic/css/colors/default.css",
        "core/vendor/cubic/js/custom.js",
        "core/vendor/cubic/js/sidebarmenu.js",
        "core/vendor/cubic/js/jquery.slimscroll.js",
        "core/vendor/cubic/js/waves.js",
        "core/vendor/cubic/plugins/components/jquery/dist/jquery.min.js",
        "core/vendor/cubic/plugins/images/favicon.png",
        "core/vendor/cubic/plugins/images/login-register.jpg",
        "core/vendor/cubic/less/icons/simple-line-icons/fonts/Simple-Line-Icons.woff2",
        "core/vendor/cubic/less/icons/themify-icons/fonts/themify.woff",
        "core/vendor/cubic/less/icons/font-awesome/fonts/fontawesome-webfont.woff2",
        "core/vendor/cubic/less/icons/material-design-iconic-font/css/materialdesignicons.min.css",
        "core/vendor/cubic/less/icons/material-design-iconic-font/fonts/materialdesignicons-webfont.woff2",
        "core/css/cubic-overrides.css",
    ]

    def test_required_cubic_assets_are_checked_in(self) -> None:
        for asset in self.required_assets:
            with self.subTest(asset=asset):
                self.assertTrue((settings.BASE_DIR / "core/static" / asset).exists())

    def test_project_templates_do_not_reference_html_template(self) -> None:
        template_paths = (settings.BASE_DIR).glob("**/templates/**/*.html")
        offenders = [
            path for path in template_paths
            if "html_template/" in path.read_text(encoding="utf-8")
        ]
        self.assertEqual(offenders, [])

    def test_templates_do_not_mix_bootstrap_and_pg_toggle_on_same_tag(self) -> None:
        pattern = re.compile(r"<[^>]*(data-toggle=)[^>]*(data-pg-toggle=)|<[^>]*(data-pg-toggle=)[^>]*(data-toggle=)", re.DOTALL)
        offenders = []
        for path in (settings.BASE_DIR).glob("**/templates/**/*.html"):
            text = path.read_text(encoding="utf-8")
            if pattern.search(text):
                offenders.append(str(path.relative_to(settings.BASE_DIR)))
        self.assertEqual(offenders, [])
```

Import `re` and `django.conf.settings` if they are not already imported.

- [ ] **Step 2: Run static guard tests to verify they fail**

Run: `python manage.py test core.tests.CubicStaticAssetTests -q`

Expected: FAIL because `core/static/core/vendor/cubic/...` and `core/css/cubic-overrides.css` do not exist.

- [ ] **Step 3: Copy the minimal Cubic static assets**

Create the target directories and copy only:

- `html_template/Cubic/cubic-html/bootstrap/dist/css/bootstrap.min.css`
- `html_template/Cubic/cubic-html/bootstrap/dist/js/bootstrap.min.js`
- all files under `html_template/Cubic/cubic-html/bootstrap/dist/fonts/`
- `html_template/Cubic/cubic-html/css/style.css`
- `html_template/Cubic/cubic-html/css/spinners.css`
- `html_template/Cubic/cubic-html/css/animate.css`
- `html_template/Cubic/cubic-html/css/colors/default.css`
- `html_template/Cubic/cubic-html/js/custom.js`
- `html_template/Cubic/cubic-html/js/sidebarmenu.js`
- `html_template/Cubic/cubic-html/js/jquery.slimscroll.js`
- `html_template/Cubic/cubic-html/js/waves.js`
- `html_template/Cubic/plugins/components/jquery/dist/jquery.min.js`
- `html_template/Cubic/plugins/images/favicon.png`
- `html_template/Cubic/plugins/images/login-register.jpg`
- all files under `html_template/Cubic/cubic-html/less/icons/simple-line-icons/fonts/`
- all files under `html_template/Cubic/cubic-html/less/icons/themify-icons/fonts/`
- all files under `html_template/Cubic/cubic-html/less/icons/font-awesome/fonts/`
- `html_template/Cubic/cubic-html/less/icons/material-design-iconic-font/css/materialdesignicons.min.css`
- all files under `html_template/Cubic/cubic-html/less/icons/material-design-iconic-font/fonts/`

Do not copy source maps or package/source directories beyond those listed.

- [ ] **Step 4: Create `core/static/core/css/cubic-overrides.css`**

Add these scoped shell fixes:

```css
.puri-cubic-logo {
  color: #ffffff;
  font-weight: 700;
}

.puri-cubic-logo:hover,
.puri-cubic-logo:focus {
  color: #ffffff;
  text-decoration: none;
}
```

- [ ] **Step 5: Run static guard tests**

Run: `python manage.py test core.tests.CubicStaticAssetTests -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add core/tests.py core/static/core/vendor/cubic core/static/core/css/cubic-overrides.css
git commit -m "Add Cubic static asset layer"
```

## Task 2: Authenticated Cubic Base Shell

**Files:**
- Modify: `core/tests.py`
- Modify: `core/templates/base.html`

**Interfaces:**
- Consumes: Cubic static paths from Task 1.
- Produces: `base.html` with Cubic `#wrapper`, `.navbar-header`, `.sidebar`, `#side-menu`, `.page-wrapper`, and `.container-fluid`.
- Preserves: `{% block title %}`, `{% block extra_css %}`, `{% block content %}`, `{% block extra_js %}`.

- [ ] **Step 1: Write failing base template tests in `core/tests.py`**

Add `CubicBaseTemplateTests(SimpleTestCase)` with a helper that reads `core/templates/base.html`.

Test names and assertions:

```python
def test_base_links_cubic_css_before_design_system(self) -> None:
    content = self.base_template()
    self.assertLess(content.index("core/vendor/cubic/bootstrap/dist/css/bootstrap.min.css"), content.index("core/css/design-system.css"))
    self.assertLess(content.index("core/vendor/cubic/css/style.css"), content.index("core/css/design-system.css"))
    self.assertLess(content.index("core/css/design-system.css"), content.index("core/css/cubic-overrides.css"))

def test_base_links_scripts_in_dependency_order(self) -> None:
    content = self.base_template()
    expected = [
        "core/vendor/cubic/plugins/components/jquery/dist/jquery.min.js",
        "core/vendor/cubic/bootstrap/dist/js/bootstrap.min.js",
        "core/vendor/cubic/js/sidebarmenu.js",
        "core/vendor/cubic/js/jquery.slimscroll.js",
        "core/vendor/cubic/js/waves.js",
        "core/vendor/cubic/js/custom.js",
        "core/js/design-system.js",
        "{% block extra_js %}",
    ]
    positions = [content.index(item) for item in expected]
    self.assertEqual(positions, sorted(positions))

def test_base_uses_cubic_shell_structure(self) -> None:
    content = self.base_template()
    self.assertIn('id="wrapper"', content)
    self.assertIn('class="navbar-header"', content)
    self.assertIn('class="sidebar"', content)
    self.assertIn('id="side-menu"', content)
    self.assertIn('class="page-wrapper"', content)

def test_base_preserves_required_template_blocks(self) -> None:
    content = self.base_template()
    for block in ["title", "extra_css", "content", "extra_js"]:
        self.assertIn(f"{{% block {block} %}}", content)

def test_base_keeps_fontawesome_6_for_existing_icons(self) -> None:
    self.assertIn("cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css", self.base_template())

def test_base_keeps_logout_as_post_with_csrf(self) -> None:
    content = self.base_template()
    self.assertIn('method="post"', content)
    self.assertIn("{% csrf_token %}", content)
    self.assertIn("{% url 'core:logout' %}", content)

def test_base_has_no_sample_cubic_content(self) -> None:
    content = self.base_template()
    for sample in ["Hanna Gover", "Buy Cubic Admin", "See all notifications", "Task 1", "eCommerce"]:
        self.assertNotIn(sample, content)
```

- [ ] **Step 2: Run base template tests to verify they fail**

Run: `python manage.py test core.tests.CubicBaseTemplateTests -q`

Expected: FAIL because `base.html` is still the current `pg-*` shell.

- [ ] **Step 3: Replace `core/templates/base.html` with the Cubic authenticated shell**

Implement:

- `{% load static %}` stays at the top.
- Head links in this order:
  1. Cubic Bootstrap CSS.
  2. Cubic `animate.css`.
  3. Cubic `style.css`.
  4. Cubic `colors/default.css`.
  5. Existing Font Awesome 6 CDN.
  6. Existing `core/css/design-system.css`.
  7. New `core/css/cubic-overrides.css`.
  8. `{% block extra_css %}`.
- Body uses `class="mini-sidebar"` and contains `.preloader`.
- Authenticated shell uses Cubic wrapper, top nav, mobile toggle, sidebar, and page wrapper.
- Sidebar menu includes:
  - Inicio: `{% url 'core:home' %}`
  - Clientes: `{% url 'clients:list' %}`
  - Pedidos: `{% url 'orders:list' %}`
  - Rutas: `{% url 'routes:list' %}`
  - Confirmaciones: `{% url 'route_confirmations:list' %}`
  - Recordatorios: `{% url 'reminders:list' %}`
  - Reportes submenu: orders report, breakdown payment method, credit report, pending payments.
  - Administrador submenu only when `user.is_staff`: existing admin order/client/product/category/route/invoice URLs.
- Main content lives inside `.page-wrapper > .container-fluid`.
- Messages render in `.container-fluid` with Bootstrap `alert alert-dismissible` classes and `data-dismiss="alert"`.
- Footer copy remains PuriGest/Gestion Purificadora.
- Scripts load in the order pinned by the test.

- [ ] **Step 4: Run base template tests**

Run: `python manage.py test core.tests.CubicBaseTemplateTests core.tests.CubicStaticAssetTests -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/templates/base.html core/tests.py
git commit -m "Migrate base shell to Cubic"
```

## Task 3: Cubic Auth Base And Login Page

**Files:**
- Modify: `core/tests.py`
- Create: `core/templates/base_auth.html`
- Modify: `core/templates/registration/login.html`

**Interfaces:**
- Consumes: Cubic static paths from Task 1.
- Produces: `base_auth.html` for auth pages without the authenticated sidebar.
- Produces: login page preserving Django auth field names and hidden `next`.

- [ ] **Step 1: Write failing auth/login tests in `core/tests.py`**

Add `CubicAuthTemplateTests(SimpleTestCase)` with helpers for `base_auth.html` and `registration/login.html`.

Test names and assertions:

```python
def test_login_extends_base_auth(self) -> None:
    self.assertIn("{% extends 'base_auth.html' %}", self.login_template())

def test_auth_base_links_cubic_assets_without_sidebar(self) -> None:
    content = self.auth_base_template()
    self.assertIn("core/vendor/cubic/bootstrap/dist/css/bootstrap.min.css", content)
    self.assertIn("core/vendor/cubic/css/style.css", content)
    self.assertIn("core/vendor/cubic/js/custom.js", content)
    self.assertIn("{% block content %}", content)
    self.assertNotIn('id="side-menu"', content)
    self.assertNotIn('class="sidebar"', content)

def test_login_preserves_django_auth_fields(self) -> None:
    content = self.login_template()
    self.assertIn("{% csrf_token %}", content)
    self.assertIn('name="{{ form.username.name }}"', content)
    self.assertIn('name="{{ form.password.name }}"', content)
    self.assertIn('name="next"', content)
    self.assertIn("{{ next }}", content)

def test_login_uses_spanish_copy_and_no_cubic_sample_links(self) -> None:
    content = self.login_template()
    self.assertIn("Iniciar Sesion", strip_accents(content))
    self.assertIn("Usuario", content)
    self.assertIn("Contrasena", strip_accents(content))
    for sample in ["Forgot pwd", "Facebook", "Google", "register.html", "Sign Up"]:
        self.assertNotIn(sample, content)
```

Use a small local `strip_accents(value: str) -> str` test helper based on `unicodedata.normalize` if the assertions need accent-insensitive checks.

- [ ] **Step 2: Run auth/login tests to verify they fail**

Run: `python manage.py test core.tests.CubicAuthTemplateTests -q`

Expected: FAIL because `base_auth.html` does not exist and login still extends `base.html`.

- [ ] **Step 3: Create `core/templates/base_auth.html`**

Use Cubic's login shell shape:

- Load the same CSS stack as `base.html`: Cubic CSS, Font Awesome 6 CDN, `core/css/design-system.css`, `core/css/cubic-overrides.css`, then `extra_css`.
- Use body class `mini-sidebar`.
- Include `.preloader`.
- Wrap content with `<section id="wrapper" class="login-register">`.
- Expose `{% block title %}`, `{% block extra_css %}`, `{% block content %}`, and `{% block extra_js %}`.
- Load the same Cubic JS dependency stack before `core/js/design-system.js`, then `extra_js`.
- Do not include authenticated sidebar/top nav markup.

- [ ] **Step 4: Update `core/templates/registration/login.html`**

Change it to extend `base_auth.html` and use Cubic login markup:

- `.login-box > .white-box`.
- `<form class="form-horizontal form-material" method="post">`.
- Spanish title `Iniciar Sesión`.
- Preserve form errors and non-field errors.
- Preserve `name="{{ form.username.name }}"`, `name="{{ form.password.name }}"`, CSRF, and hidden `next`.
- Submit button text: `Iniciar Sesión`.
- No recover-password, social login, registration, or sample links.

- [ ] **Step 5: Run auth/login tests**

Run: `python manage.py test core.tests.CubicAuthTemplateTests core.tests.CubicStaticAssetTests core.tests.CubicBaseTemplateTests -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add core/templates/base_auth.html core/templates/registration/login.html core/tests.py
git commit -m "Migrate login to Cubic auth shell"
```

## Task 4: Verification And Cleanup

**Files:**
- Modify only files needed to fix verification failures from Tasks 1-3.

**Interfaces:**
- Consumes: completed Cubic assets, base shell, and auth shell.
- Produces: a verified first-pass Cubic UI migration.

- [ ] **Step 1: Run focused template/static tests**

Run: `python manage.py test core.tests.CubicStaticAssetTests core.tests.CubicBaseTemplateTests core.tests.CubicAuthTemplateTests -q`

Expected: PASS.

- [ ] **Step 2: Run Django system checks**

Run: `python manage.py check`

Expected: PASS.

- [ ] **Step 3: Run existing core tests**

Run: `python manage.py test core -q`

Expected: PASS. If unrelated pre-existing failures appear, record them by test name in the final report.

- [ ] **Step 4: Run collectstatic dry run**

Run: `python manage.py collectstatic --dry-run --noinput`

Expected: PASS without missing-file errors from Cubic CSS `url(...)` references.

- [ ] **Step 5: Inspect changed file list for JavaScript edits**

Run: `git diff --name-only 7ca4420..HEAD -- core/static/core/js orders/static clients/static routes/static invoice/static`

Expected: no files listed. New copied Cubic vendor JS under `core/static/core/vendor/cubic/` is allowed and intentionally excluded from this check.

- [ ] **Step 6: Optional local visual check**

If dependencies and database settings allow starting the app locally, run `make runserver` and inspect:

- Anonymous login page.
- Authenticated home/dashboard.
- Clients list.
- Create order page.
- Routes list.
- A report page with existing `pg-*` dropdown/modal behavior.

Expected: Cubic shell renders, sidebar toggles, existing `pg-*` interactions still work.

- [ ] **Step 7: Commit verification fixes if any**

If Task 4 required fixes:

Stage only the files changed to fix Task 4 failures, then run:

```bash
git commit -m "Verify Cubic shell migration"
```
