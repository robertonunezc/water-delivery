# Cubic Template UI Migration Design

## Context

The repository already has a custom Django UI foundation:

- `core/templates/base.html` provides the shared authenticated shell.
- `core/static/core/css/design-system.css` provides `pg-*` layout, form, table, card, modal, tab, dropdown, and utility classes.
- `core/static/core/js/design-system.js` provides vanilla behavior for `data-pg-*` dropdowns, tabs, modals, collapses, nav toggles, and dismiss buttons.
- Many app templates extend `base.html` and rely on `pg-*` classes.

The `html_template` folder contains the Cubic Admin scaffold at `html_template/Cubic`. The relevant source files are:

- `html_template/Cubic/cubic-html/starter-page.html` for the authenticated layout scaffold.
- `html_template/Cubic/cubic-html/login.html` for the login layout.
- `html_template/Cubic/cubic-html/bootstrap/dist` for Bootstrap 3.3.7.
- `html_template/Cubic/cubic-html/css/style.css`, `css/animate.css`, and `css/colors/default.css` for Cubic styling.
- `html_template/Cubic/cubic-html/js/custom.js`, `sidebarmenu.js`, `jquery.slimscroll.js`, and `waves.js` for Cubic behavior.
- `html_template/Cubic/plugins/components/jquery/dist/jquery.min.js` for jQuery 2.1.4.
- `html_template/Cubic/plugins/images` and `cubic-html/less/icons` for logos, favicon, and icon fonts referenced by Cubic CSS.

Cubic is a Bootstrap 3 and jQuery admin template. It expects markup such as `.navbar-header`, `.sidebar`, `#side-menu`, `.page-wrapper`, `.preloader`, `.sidebartoggler`, `data-toggle`, `.collapse`, `.dropdown-menu`, and Bootstrap grid classes. The current project expects `pg-*` classes and `data-pg-*` attributes. The migration must bridge these systems without breaking existing page behavior.

## Goals

- Use the Cubic scaffold as the app shell for project-owned non-Django-admin pages.
- Keep all existing project JavaScript code unchanged.
- Allow linking Cubic vendor JavaScript after checking compatibility.
- Preserve current Django URLs, views, forms, submissions, messages, permissions, and Spanish/Mexico business copy.
- Preserve existing `data-pg-*` behavior for page-level dropdowns, tabs, modals, collapses, and order workflows until each page is intentionally migrated.
- Copy only the required Cubic static assets into application static paths instead of serving from `html_template`.
- Add tests that protect the asset contract and catch unsafe mixed-control markup.
- Keep the migration incremental so the shared shell can change first without requiring every page template to be rewritten at once.

## Non-Goals

- Do not edit existing JavaScript files in this migration.
- Do not replace Django views, forms, models, services, or business logic.
- Do not migrate Django/Unfold admin internals to Cubic.
- Do not copy the full 45 MB Cubic scaffold or sample pages into collected static files.
- Do not add Node, npm, bundlers, Tailwind, React, or a frontend build step.
- Do not remove `pg-*` CSS/classes from every page in the first pass.
- Do not put both `data-toggle` and `data-pg-toggle` on the same interactive element.

## Architecture

The migration should add a Cubic asset layer under `core/static/core/vendor/cubic/` and then adapt shared templates to use the Cubic shell.

Recommended static structure:

- `core/static/core/vendor/cubic/bootstrap/`
- `core/static/core/vendor/cubic/css/`
- `core/static/core/vendor/cubic/js/`
- `core/static/core/vendor/cubic/plugins/`
- `core/static/core/vendor/cubic/images/`
- `core/static/core/vendor/cubic/less/icons/`
- `core/static/core/css/cubic-overrides.css`

The copied Cubic assets must keep relative paths intact where Cubic CSS references fonts or images. If a CSS file references `../less/icons/...`, the copied static directory must preserve that relationship.

`core/templates/base.html` becomes the first Cubic-backed layout. It should:

- Load Cubic CSS before the project design-system CSS when the page still contains `pg-*` components.
- Keep `core/css/design-system.css` loaded so existing page content does not lose styling.
- Load `core/css/cubic-overrides.css` last for PuriGest-specific adjustments.
- Render Cubic's `#wrapper`, top nav, left sidebar, `.page-wrapper`, `.container-fluid`, and footer.
- Use real Django navigation links for Clientes, Rutas, Confirmaciones, Recordatorios, Reportes, Administrador, and the user logout form.
- Use Cubic sidebar structure and `#side-menu` so `sidebarmenu.js` and `custom.js` can operate.
- Keep `{% block title %}`, `{% block extra_css %}`, `{% block content %}`, and `{% block extra_js %}` unchanged as public template extension points.

`tenant_client/templates/tenant_client/base_tenant.html` stays on the current minimal shell in the first migration. Tenant management pages can adopt Cubic in a follow-up after the primary authenticated shell is stable.

`core/templates/registration/login.html` should be migrated separately using Cubic's `login.html` structure because it does not need the full sidebar shell.

## JavaScript Compatibility

Existing project JavaScript is frozen. The migration may add and link Cubic vendor JavaScript, but must not edit these files:

- `core/static/core/js/design-system.js`
- files under `orders/static/`
- files under `clients/static/`
- files under `routes/static/`
- files under `invoice/static/`
- inline page scripts in existing templates

Cubic scripts should be loaded in this order:

1. `core/vendor/cubic/plugins/components/jquery/dist/jquery.min.js`
2. `core/vendor/cubic/bootstrap/dist/js/bootstrap.min.js`
3. `core/vendor/cubic/js/sidebarmenu.js`
4. `core/vendor/cubic/js/jquery.slimscroll.js`
5. `core/vendor/cubic/js/waves.js`
6. `core/vendor/cubic/js/custom.js`
7. `core/js/design-system.js`
8. `{% block extra_js %}`

The order intentionally initializes Cubic shell behavior before the existing `pg-*` behavior. Cubic listens to Bootstrap/jQuery selectors and `data-toggle`; `design-system.js` listens to `data-pg-toggle` and `data-pg-dismiss`. They can coexist if markup keeps those contracts separate.

Compatibility risks and decisions:

- Cubic's `custom.js` calls Bootstrap plugins such as `.tooltip()`, `.popover()`, and `.collapse()`. Bootstrap JS must be present before `custom.js`.
- Cubic's `custom.js` initializes `#side-menu` with MetisMenu through `sidebarmenu.js`. The base sidebar must include `#side-menu`.
- Cubic's `custom.js` uses `.preloader`, `.sidebartoggler`, `.navbar-toggle`, `.scroll-sidebar`, `.page-wrapper`, `.right-sidebar`, `.fxhdr`, and `.fxsdr`. The base shell should include only the elements needed for normal navigation and may omit right-sidebar controls if the matching trigger is also omitted.
- Existing `pg-*` dropdowns, tabs, modals, and collapses should keep `data-pg-*` attributes and should not also receive Bootstrap `data-toggle`.
- New Cubic shell controls should use Cubic/Bootstrap selectors and should not use `data-pg-*`.
- If a page is converted from `pg-*` controls to Bootstrap controls later, that conversion must be page-scoped and tested.

## Template Migration Strategy

The migration should happen in layers.

### Layer 1: Static Assets And Guards

Copy the required Cubic files into `core/static/core/vendor/cubic/`. Keep paths minimal but complete enough for the base shell, login page, icons, fonts, logo, favicon, sidebar, and Bootstrap behavior.

Add tests in `core/tests.py` or a focused UI/static test module that assert:

- Required Cubic CSS, JS, image, and font files exist.
- `base.html` links the required Cubic CSS and JS assets through `{% static %}`.
- `base.html` still links `core/css/design-system.css` and `core/js/design-system.js`.
- No project-owned template contains both `data-toggle` and `data-pg-toggle` on the same tag.
- No project-owned template links directly to `html_template/`.

### Layer 2: Shared Authenticated Shell

Update `core/templates/base.html` to use Cubic's scaffold. The content block should live inside Cubic's `.page-wrapper > .container-fluid` area.

The sidebar should be operationally focused:

- Inicio
- Clientes
- Pedidos
- Rutas
- Confirmaciones
- Recordatorios
- Reportes
- Administrador, only for staff users

The top nav should keep:

- Sidebar toggle
- PuriGest brand
- Authenticated user name
- Logout POST form with CSRF

Django messages should render in the page content area using Bootstrap alert classes and Bootstrap's `data-dismiss="alert"`. They should not use `data-pg-dismiss` in the Cubic shell.

### Layer 3: Login Shell

Update `core/templates/registration/login.html` to match Cubic's login page while preserving Django authentication fields, CSRF, `next`, form errors, and Spanish copy.

The login template should not load the authenticated sidebar. Introduce `core/templates/base_auth.html` for Cubic auth pages instead of adding sidebar conditionals to `base.html`.

### Layer 4: Page Content Increment

Keep existing page content mostly `pg-*` in the first implementation. That avoids rewriting high-risk workflows such as:

- `orders/templates/create_order.html`
- `clients/templates/client_detail.html`
- `clients/templates/clients/client_form_v2.html`
- `report/templates/report/orders_report.html`

After the shell is stable, migrate individual pages or components to Cubic classes only where the value is clear and tests can pin behavior.

## CSS Compatibility

Cubic and the existing design system both style global elements such as `body`, tables, buttons, alerts, modals, and layout containers. To reduce surprises:

- Load Cubic CSS first.
- Load `core/css/design-system.css` after Cubic so existing `pg-*` components keep their current appearance.
- Load `core/css/cubic-overrides.css` last for shell-specific fixes.
- Scope new overrides to Cubic shell selectors where possible, such as `#wrapper`, `.sidebar`, `.page-wrapper`, `.navbar-header`, and `.puri-cubic-*`.
- Avoid changing broad `body`, `a`, `button`, `input`, `table`, `.row`, or `.container-fluid` styles in overrides unless the impact is reviewed.

The Cubic color theme imports Google Fonts in `css/colors/default.css`. The first migration accepts that import as part of the vendor template and must not introduce any additional remote font source.

## Static Asset Scope

Do copy:

- Bootstrap dist CSS, JS, and fonts.
- Cubic `css/style.css`, `css/animate.css`, `css/colors/default.css`.
- Cubic `js/custom.js`, `js/sidebarmenu.js`, `js/jquery.slimscroll.js`, `js/waves.js`.
- jQuery from `plugins/components/jquery/dist/jquery.min.js`.
- Images used by the shell, favicon, logo, and login background.
- Icon font directories referenced by `style.css`.

Do not copy:

- Cubic sample HTML pages.
- Documentation.
- Demo data scripts like dashboard chart samples unless a migrated page uses them.
- Unused plugins such as maps, calendars, editors, galleries, DataTables, Dropzone, and chart libraries in the initial pass.
- `.DS_Store`, source maps, package metadata, Grunt files, or LESS source not needed by referenced CSS paths.

## Testing And Verification

Automated verification should include:

- Focused static/template tests for asset links and mixed-control rules.
- `python manage.py check`.
- Focused tests for auth/login rendering if existing test setup supports it.
- Existing app tests that exercise pages with `pg-*` interactions where feasible.

Manual verification should include representative pages:

- Anonymous login page.
- Authenticated home/dashboard.
- Clients list and client detail.
- Create order page.
- Routes list/detail.
- Reports page with modal/dropdown usage.
- Mobile viewport sidebar toggle.

Manual checks:

- Sidebar opens/collapses on desktop and mobile.
- Existing `pg-*` dropdowns still open and close.
- Existing `pg-*` modals still open and close.
- Existing `pg-*` tabs still switch.
- Logout remains a POST with CSRF.
- No visible sample Cubic user names, messages, ecommerce links, or "Buy Cubic Admin" controls remain.

## Rollout

The first shippable implementation should stop after Cubic assets, base shell, login shell, tests, and verification. It should not attempt a full page-by-page rewrite.

Follow-up migrations can convert individual pages to Cubic markup when a page needs visual cleanup or when its interaction model can safely move from `data-pg-*` to Bootstrap `data-toggle`.

## Open Decisions Resolved

- Existing project JavaScript remains unchanged.
- Cubic vendor JavaScript may be linked after compatibility checks.
- The migration will use Cubic as the shared scaffold and keep existing `pg-*` content behavior in the first pass.
- The migration will avoid mixed `data-toggle` and `data-pg-toggle` controls on the same element.
