# Reminders Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a personal one-time reminders module with user-owned CRUD, dashboard visibility, route-client awareness, completion, soft-delete, and admin visibility.

**Architecture:** Add a new `reminders` Django app for models, forms, views, templates, services, admin, and tests. Keep route/date visibility in a reminder service so dashboard views and templates stay thin. Use the existing `TimeStampedModel` soft-delete pattern and existing route ownership model: `User -> Employee -> Transport.assigned_driver -> Route -> RouteClient.due_on(today)`.

**Tech Stack:** Django 5.2, django-tenants test base `FastTenantTestCase`, Unfold admin, existing `pg-*` design system classes, Font Awesome icons.

**Spec:** `docs/superpowers/specs/2026-09-28-reminders-design.md`

## Global Constraints

- New app/module name is `reminders`; UI labels are Spanish `Recordatorios`.
- Reminders are one-time only; no recurrence.
- Reminder date is date-only; no time-of-day behavior.
- Any authenticated user with normal app access can create and manage their own reminders.
- Normal user-facing views are owner-scoped; admins/superusers can see all reminders in Django admin.
- `title` is required; `description`, `client`, and `reminder_date` are optional.
- `urgent` is an optional boolean; urgent reminders sort first and render highlighted.
- `LISTO` sets `completed_at` and `completed_by`; completed reminders are read-only in user-facing edit flows.
- `Eliminar` soft-deletes using `deleted_at` and is distinct from `LISTO`.
- Home reminders appear near the top of `home.html`, `delivery_dashboard.html`, and `manager_dashboard.html`.
- Past-dated incomplete reminders do not appear on home; they appear in the `Vencidos` list filter.

## Review Focus

- Users without `Employee`, `Transport`, or a today route still see date/no-date reminders and get no route errors; covered in Task 2 service tests.
- Future-dated client reminders for today-route clients appear only in the lower-priority route-context group, not the main today group; covered in Task 2 service tests.
- Owner scoping prevents another user from listing, editing, completing, or deleting someone else's reminder; covered in Task 3 view tests.
- Completed reminders are visible under `Listos` but cannot be edited; covered in Task 3 view tests.
- Invalid `?client=<id>` create preselection renders the create form without failing; covered in Task 3 view tests.

---

## File Structure

- Create `reminders/apps.py`: app config.
- Create `reminders/models.py`: `Reminder`, `ReminderQuerySet`, `ReminderManager`, completion helpers.
- Create `reminders/admin.py`: full admin visibility with useful filters and soft-delete mixin.
- Create `reminders/forms.py`: `ReminderForm` with Spanish labels and optional client/date/urgent fields.
- Create `reminders/services.py`: home grouping, route-client lookup, complete/delete orchestration.
- Create `reminders/views.py`: authenticated list/create/edit/complete/delete views.
- Create `reminders/urls.py`: `recordatorios/` route names.
- Create `reminders/tests.py`: model, service, and view tests using `FastTenantTestCase`.
- Create `reminders/templates/reminders/list.html`: user-facing list/search/filter page.
- Create `reminders/templates/reminders/form.html`: dedicated create/edit page.
- Create `reminders/templates/reminders/_home_block.html`: shared dashboard reminder block.
- Create `reminders/templates/reminders/_reminder_row.html`: reusable reminder row/card partial used by the list page and the home reminder block.
- Modify `water_delivery/settings.py`: add `reminders` to `TENANT_APPS`.
- Modify `water_delivery/urls.py`: include `reminders.urls` under `recordatorios/`.
- Modify `core/templates/base.html`: add `NUEVO RECORDATORIO` and `Recordatorios` navigation for authenticated users.
- Modify `core/views.py` and `core/services/dashboard_service.py`: include reminder context for all authenticated home variants.
- Modify `core/templates/home.html`, `core/templates/delivery_dashboard.html`, `core/templates/manager_dashboard.html`: include the home reminder block near the top.
- Modify `clients/templates/client_detail.html`: add client-specific `NUEVO RECORDATORIO` button with `?client={{ client.pk }}`.

## Task 1: Reminder App, Model, Querysets, Admin

**Files:**
- Create: `reminders/__init__.py`
- Create: `reminders/apps.py`
- Create: `reminders/models.py`
- Create: `reminders/admin.py`
- Create: `reminders/migrations/__init__.py`
- Modify: `water_delivery/settings.py`
- Test: `reminders/tests.py`

**Interfaces:**
- Produces: `Reminder` model with fields `title`, `description`, `client`, `reminder_date`, `urgent`, `created_by`, `completed_at`, `completed_by`.
- Produces: `Reminder.objects.for_user(user)`, `.active()`, `.completed()`, `.overdue(today)`, `.not_overdue(today)`, `.urgent_first()`.
- Produces: `Reminder.mark_completed(user: User, completed_at: datetime | None = None) -> None`.

- [ ] **Step 1: Write failing model/queryset tests in `reminders/tests.py`**

Test names and assertions:
- `ReminderQuerySetTests.test_active_excludes_completed_and_deleted`
- `ReminderQuerySetTests.test_overdue_finds_incomplete_past_dated_reminders`
- `ReminderQuerySetTests.test_completed_returns_completed_non_deleted_reminders`
- `ReminderQuerySetTests.test_for_user_scopes_to_creator`
- `ReminderQuerySetTests.test_urgent_first_orders_urgent_before_normal`
- `ReminderModelTests.test_mark_completed_sets_timestamp_and_user`

- [ ] **Step 2: Run model tests to verify they fail**

Run: `python manage.py test reminders -q`
Expected: FAIL because the `reminders` app/model does not exist yet.

- [ ] **Step 3: Implement app config, settings registration, model, manager, and admin**

Implement:
- `class RemindersConfig(AppConfig)` with `name = "reminders"`.
- Add `"reminders"` to `TENANT_APPS` in `water_delivery/settings.py`.
- `class Reminder(TimeStampedModel)` in `reminders/models.py`.
- `ReminderQuerySet` and manager with the exact interfaces above.
- `mark_completed()` should no-op on already completed reminders to preserve original metadata.
- Admin should extend `SoftDeleteAdminMixin, ModelAdmin` and use `Reminder.all_objects` if needed to inspect deleted records.

- [ ] **Step 4: Create migration**

Run: `python manage.py makemigrations reminders`
Expected: a migration creating `reminders_reminder`.

- [ ] **Step 5: Run model tests**

Run: `python manage.py test reminders -q`
Expected: PASS for model/queryset tests.

- [ ] **Step 6: Commit**

```bash
git add water_delivery/settings.py reminders docs/superpowers/plans/2026-09-28-reminders.md
git commit -m "Add reminder model"
```

## Task 2: Reminder Services And Home Visibility

**Files:**
- Create: `reminders/services.py`
- Modify: `reminders/tests.py`

**Interfaces:**
- Consumes: `Reminder` model/queryset from Task 1.
- Produces: `get_user_route_client_ids(user: User, target_date: date | None = None) -> set[int]`.
- Produces: `get_home_reminder_context(user: User, today: date | None = None) -> dict[str, list[Reminder]]` with keys `today_reminders` and `route_context_reminders`.
- Produces: `complete_reminder(reminder: Reminder, user: User) -> Reminder`.
- Produces: `soft_delete_reminder(reminder: Reminder, user: User) -> None`.

- [ ] **Step 1: Write failing service tests in `reminders/tests.py`**

Test names and assertions:
- `ReminderHomeServiceTests.test_no_date_no_client_reminder_appears_today`
- `ReminderHomeServiceTests.test_today_dated_reminder_appears_today`
- `ReminderHomeServiceTests.test_past_dated_reminder_is_excluded_from_home`
- `ReminderHomeServiceTests.test_client_only_reminder_appears_when_client_is_in_user_route`
- `ReminderHomeServiceTests.test_future_client_route_reminder_is_route_context_only`
- `ReminderHomeServiceTests.test_route_lookup_without_employee_transport_or_route_is_empty`
- `ReminderServiceActionTests.test_complete_reminder_requires_owner`
- `ReminderServiceActionTests.test_soft_delete_reminder_requires_owner`

- [ ] **Step 2: Run service tests to verify they fail**

Run: `python manage.py test reminders -q`
Expected: FAIL because `reminders.services` functions do not exist.

- [ ] **Step 3: Implement `get_user_route_client_ids()`**

Use:
- `user.employee`
- `Transport.objects.filter(assigned_driver=employee, is_active=True).first()`
- `Route.get_today_routes(transportation=transportation).first()`
- `RouteClient.objects.due_on(current_date).filter(route=today_route).values_list("client_id", flat=True)`

Return an empty set for missing employee/transport/route.

- [ ] **Step 4: Implement `get_home_reminder_context()`**

Build owner-scoped active reminders and split into:
- `today_reminders`: no date/no client, date today, or no date/client in route.
- `route_context_reminders`: future date/client in route.

Sort urgent first. Use `timezone.localdate()` when `today` is not provided.

- [ ] **Step 5: Implement `complete_reminder()` and `soft_delete_reminder()`**

Raise `PermissionDenied` when `reminder.created_by_id != user.id`. `complete_reminder()` calls `reminder.mark_completed(user)`.

- [ ] **Step 6: Run service tests**

Run: `python manage.py test reminders -q`
Expected: PASS for model and service tests.

- [ ] **Step 7: Commit**

```bash
git add reminders/services.py reminders/tests.py
git commit -m "Add reminder visibility services"
```

## Task 3: User-Facing Forms, Views, URLs

**Files:**
- Create: `reminders/forms.py`
- Create: `reminders/views.py`
- Create: `reminders/urls.py`
- Modify: `water_delivery/urls.py`
- Modify: `reminders/tests.py`

**Interfaces:**
- Consumes: services from Task 2.
- Produces URL names: `reminders:list`, `reminders:create`, `reminders:edit`, `reminders:complete`, `reminders:delete`.
- Produces `ReminderForm` exposing `title`, `description`, `client`, `reminder_date`, `urgent`.

- [ ] **Step 1: Write failing view/form tests in `reminders/tests.py`**

Test names and assertions:
- `ReminderViewTests.test_create_requires_authentication`
- `ReminderViewTests.test_create_sets_created_by_and_redirects_home`
- `ReminderViewTests.test_create_with_client_query_preselects_client`
- `ReminderViewTests.test_create_with_invalid_client_query_does_not_fail`
- `ReminderViewTests.test_list_default_shows_active_future_and_no_date_only`
- `ReminderViewTests.test_list_vencidos_filter_shows_past_incomplete`
- `ReminderViewTests.test_list_listos_filter_shows_completed_read_only`
- `ReminderViewTests.test_search_filters_title_and_description`
- `ReminderViewTests.test_client_filter_limits_results`
- `ReminderViewTests.test_edit_is_owner_only`
- `ReminderViewTests.test_completed_reminder_cannot_be_edited`
- `ReminderViewTests.test_complete_action_sets_completed_fields`
- `ReminderViewTests.test_delete_action_soft_deletes`
- `ReminderViewTests.test_other_user_cannot_complete_or_delete`

- [ ] **Step 2: Run view tests to verify they fail**

Run: `python manage.py test reminders -q`
Expected: FAIL because URLs/views/forms do not exist.

- [ ] **Step 3: Implement `ReminderForm`**

Use Spanish labels:
- `Titulo`
- `Descripcion`
- `Cliente`
- `Fecha`
- `Urgente`

Use a date input widget for `reminder_date`.

- [ ] **Step 4: Implement list view**

Require login. Scope base queryset to `Reminder.objects.for_user(request.user)`. Support:
- `status=activos` default: active and not overdue.
- `status=vencidos`: overdue.
- `status=listos`: completed.
- `q`: search title/description.
- `client`: exact client ID filter.

- [ ] **Step 5: Implement create/edit views**

Create:
- Read optional `client` query param and preselect only if a matching non-deleted client exists.
- Save `created_by=request.user`.
- Redirect to `core:home`.

Edit:
- Owner-only.
- Reject completed reminders with redirect/message.
- Redirect to `core:home` on success.

- [ ] **Step 6: Implement complete/delete POST views and URLs**

Use service functions. Redirect to `HTTP_REFERER` fallback `reminders:list`.

- [ ] **Step 7: Include reminders URLs**

Add `path('recordatorios/', include('reminders.urls'))` in `water_delivery/urls.py`.

- [ ] **Step 8: Run view/form tests**

Run: `python manage.py test reminders -q`
Expected: PASS for model, service, and view tests.

- [ ] **Step 9: Commit**

```bash
git add reminders/forms.py reminders/views.py reminders/urls.py reminders/tests.py water_delivery/urls.py
git commit -m "Add reminder views"
```

## Task 4: Templates, Navigation, Dashboard, Client Detail Integration

**Files:**
- Create: `reminders/templates/reminders/list.html`
- Create: `reminders/templates/reminders/form.html`
- Create: `reminders/templates/reminders/_home_block.html`
- Create: `reminders/templates/reminders/_reminder_row.html`
- Modify: `core/templates/base.html`
- Modify: `core/views.py`
- Modify: `core/services/dashboard_service.py`
- Modify: `core/templates/home.html`
- Modify: `core/templates/delivery_dashboard.html`
- Modify: `core/templates/manager_dashboard.html`
- Modify: `clients/templates/client_detail.html`
- Modify: `reminders/tests.py`

**Interfaces:**
- Consumes: `get_home_reminder_context(user, today)` from Task 2 and URLs from Task 3.
- Produces context keys in home templates: `today_reminders`, `route_context_reminders`.

- [ ] **Step 1: Write failing integration tests**

Test names and assertions:
- `ReminderTemplateIntegrationTests.test_base_navigation_contains_recordatorios_links_for_authenticated_user`
- `ReminderTemplateIntegrationTests.test_home_renders_reminder_block_above_dashboard_actions`
- `ReminderTemplateIntegrationTests.test_delivery_dashboard_renders_reminder_block`
- `ReminderTemplateIntegrationTests.test_manager_dashboard_renders_reminder_block`
- `ReminderTemplateIntegrationTests.test_client_detail_has_new_reminder_link_with_client_query`
- `ReminderTemplateIntegrationTests.test_urgent_reminder_renders_urgent_badge`
- `ReminderTemplateIntegrationTests.test_completed_list_rows_do_not_show_edit_link`

- [ ] **Step 2: Run integration tests to verify they fail**

Run: `python manage.py test reminders -q`
Expected: FAIL because templates/navigation are not implemented.

- [ ] **Step 3: Add shared reminder partials**

Implement `_home_block.html` for the two home groups and `_reminder_row.html` for title, optional description, linked client, date, urgent badge, and actions.

- [ ] **Step 4: Add list and form templates**

Use existing `base.html` and `pg-*` classes. List page includes status tabs/links, search input, client filter, `NUEVO RECORDATORIO`, and row actions.

- [ ] **Step 5: Add navigation links**

In `core/templates/base.html`, for authenticated users add:
- `Recordatorios` link to `reminders:list`.
- `NUEVO RECORDATORIO` action link to `reminders:create`.

- [ ] **Step 6: Add reminder context to home variants**

In `core.views.home`, add reminder context for the basic authenticated home context. In `core.services.dashboard_service.get_delivery_dashboard_context()` and `get_manager_dashboard_context()`, merge in `get_home_reminder_context(user=user, today=current_date)`.

- [ ] **Step 7: Include home block templates**

Include `reminders/_home_block.html` near the top of:
- `core/templates/home.html`
- `core/templates/delivery_dashboard.html`
- `core/templates/manager_dashboard.html`

- [ ] **Step 8: Add client detail create link**

In `clients/templates/client_detail.html`, add `NUEVO RECORDATORIO` in `.client-action-bar` linking to `{% url 'reminders:create' %}?client={{ client.pk }}`.

- [ ] **Step 9: Run integration tests**

Run: `python manage.py test reminders -q`
Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add reminders/templates core/templates core/views.py core/services/dashboard_service.py clients/templates/client_detail.html reminders/tests.py
git commit -m "Integrate reminders into dashboards"
```

## Task 5: Final Verification And Cleanup

**Files:**
- Modify: only files changed by Tasks 1-4, and only when verification exposes a reminder-specific defect.

**Interfaces:**
- Consumes all prior tasks.
- Produces a verified feature branch ready for review.

- [ ] **Step 1: Run focused reminders tests**

Run: `python manage.py test reminders -q`
Expected: PASS.

- [ ] **Step 2: Run impacted app tests**

Run: `python manage.py test reminders core routes clients -q`
Expected: PASS.

- [ ] **Step 3: Run migrations check**

Run: `python manage.py makemigrations --check --dry-run`
Expected: `No changes detected`.

- [ ] **Step 4: Run formatting/linting if practical**

Run: `make lint`
Expected: no new reminder-related lint failures. If existing unrelated lint failures appear, record them in the final response.

- [ ] **Step 5: Review git diff**

Run: `git diff --stat HEAD~4..HEAD` and `git status --short`
Expected: only intended reminders feature files changed; working tree clean except intentional uncommitted verification artifacts.

- [ ] **Step 6: Commit final cleanup if any**

```bash
git add <changed-files>
git commit -m "Polish reminders feature"
```

Skip this commit if no cleanup changes were needed.
