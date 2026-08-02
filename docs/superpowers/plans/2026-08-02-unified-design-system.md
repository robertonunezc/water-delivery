# Unified Design System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Bootstrap and page-local styling with one reusable Django design system inspired by shadcn/ui tokens and Base UI accessibility patterns.

**Architecture:** Add shared CSS variables, component classes, and a small vanilla JavaScript behavior layer under `core/static/core`. Update base layouts first, then migrate app templates and JS-generated markup to `pg-*` classes. Keep Django server-rendered templates and the existing Unfold admin, while aligning admin custom pages through shared tokens.

**Tech Stack:** Django 5.2, Django templates, static CSS, vanilla JavaScript, existing Font Awesome icons.

## Global Constraints

- Do not add a Node, React, Tailwind, shadcn/ui, or Base UI runtime.
- Remove Bootstrap CDN includes from project-owned base templates and standalone admin action templates.
- Replace Bootstrap classes with `pg-*` design-system classes in project-owned templates and JavaScript-generated markup.
- Move page-local `<style>` blocks and inline `style=` declarations into shared or page-scoped static CSS classes.
- Preserve existing URLs, form submissions, tab/collapse/modal/dropdown behavior, and Spanish copy.
- Admin pages that extend Django/Unfold admin must keep admin compatibility while avoiding new Bootstrap dependencies.
- Use accessible names, keyboard handling, focus-visible states, and ARIA state updates for custom UI behavior.

---

## File Structure

- Create `core/static/core/css/design-system.css`: global tokens and reusable component classes.
- Create `core/static/core/js/design-system.js`: dropdown, nav, tabs, modal, collapse, alert dismissal, and disable-state helpers.
- Modify `core/templates/base.html`: load shared assets and replace the Bootstrap shell.
- Modify `tenant_client/templates/tenant_client/base_tenant.html`: load shared assets and replace the Bootstrap shell.
- Modify app templates under `core`, `clients`, `orders`, `routes`, `report`, `product`, `invoice`, `templates/admin`, and `tenant_client/templates`: convert markup to `pg-*` classes and remove inline styles.
- Modify JS under `orders/static`, `routes/static`, `clients/static`, and `invoice/static`: replace generated Bootstrap classes and inline styles with `pg-*` classes.
- Modify Django form widgets in `clients/forms.py`, `orders/forms.py`, `routes/forms.py`, `product/forms.py`, and `invoice/forms.py`: emit design-system form classes.
- Modify or add tests in `core/tests.py`: assert the migration invariants.

---

### Task 1: Migration Guard Tests

- [ ] Add filesystem-based tests for required design assets and banned Bootstrap/style patterns.
- [ ] Run the focused test and confirm it fails before implementation.

### Task 2: Design System Foundation

- [ ] Create shared CSS tokens and components for layout, buttons, forms, alerts, badges, cards/panels, metrics, tables, dropdowns, tabs, modals, pagination, empty states, and mobile utilities.
- [ ] Create shared vanilla JS for interactive states formerly handled by Bootstrap.
- [ ] Update base templates to load those assets.

### Task 3: Core, Auth, Tenant Shell

- [ ] Migrate `core/templates/base.html`, home, login/logout, manager dashboard, delivery dashboard.
- [ ] Migrate tenant management base/list/create pages.
- [ ] Verify navigation, messages, login form, and dashboard responsiveness.

### Task 4: Operational App Pages

- [ ] Migrate clients pages and reusable client table include.
- [ ] Migrate orders pages, including create order modals/collapses/mobile footer.
- [ ] Migrate routes pages and admin route list/form templates.
- [ ] Migrate reports, products, and invoices pages.

### Task 5: Admin Customizations And JS

- [ ] Migrate custom admin pages and admin action templates.
- [ ] Replace JS-generated inline styles and Bootstrap classes with design-system classes.
- [ ] Keep Unfold/Django admin native classes only where required by the admin framework.

### Task 6: Verification

- [ ] Run focused migration tests.
- [ ] Run `python manage.py check`.
- [ ] Run the project test suite where feasible.
- [ ] Start the dev server and visually inspect representative pages across desktop and mobile.
- [ ] Fix remaining Bootstrap/inline-style leaks found by tests or visual review.
