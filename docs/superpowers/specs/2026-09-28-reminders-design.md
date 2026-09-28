# User Reminders Design

## Context

Users need lightweight personal reminders for operational follow-up during water delivery work. Examples include selling extra bottles to a client on the next visit or collecting bottles from a client. These reminders are internal task notes, not outbound notifications, so they should live in a new `reminders` app rather than the existing `notification` app.

The app already has recurring route assignments through `routes.RouteClient`, user-to-employee links through `core.Employee`, and driver route ownership through `core.Transport.assigned_driver`. Reminder route visibility should reuse that existing model.

## Goals

- Add a new `reminders` Django app with Spanish UI labels for `Recordatorios`.
- Let authenticated users create personal one-time reminders.
- Support reminders with a required title, optional description, optional client, optional date, and optional urgent flag.
- Add a global `NUEVO RECORDATORIO` action in the header/navigation.
- Add a `Recordatorios` page for listing, searching, filtering, editing, completing, and deleting reminders.
- Add a client-detail `NUEVO RECORDATORIO` action that opens the reminder form with the client preselected.
- Show relevant active reminders near the top of the home/dashboard pages.
- Let users mark reminders `LISTO` from any place where a reminder appears.
- Keep completed reminders read-only in user-facing screens.
- Let normal users see and manage only reminders they created.
- Let superusers/admin users inspect the full reminder list in Django admin.

## Non-Goals

- No recurring reminders.
- No time-of-day reminders; reminders use date only.
- No custom reminder permissions beyond normal authenticated app access.
- No outbound email, SMS, or WhatsApp delivery.
- No assignment to other users in this iteration.
- No shared team reminders in this iteration.

## Data Model

Create `Reminder` in a new `reminders` app. It should inherit `core.models.TimeStampedModel` for `created_at`, `updated_at`, `deleted_at`, default soft-delete behavior, and `all_objects` admin visibility.

Fields:

- `title`: required `CharField`.
- `description`: optional `TextField`.
- `client`: optional `ForeignKey` to `clients.Client`, nullable and blank.
- `reminder_date`: optional `DateField`, nullable and blank.
- `urgent`: `BooleanField`, default `False`.
- `created_by`: required `ForeignKey` to `settings.AUTH_USER_MODEL`, related name such as `reminders`.
- `completed_at`: nullable `DateTimeField`.
- `completed_by`: nullable `ForeignKey` to `settings.AUTH_USER_MODEL`, related name such as `completed_reminders`.

Rules:

- `LISTO` sets `completed_at` to `timezone.now()` and `completed_by` to the acting user.
- `Eliminar` uses the existing soft-delete path, setting `deleted_at`.
- Completed reminders remain available in the `Listos` filter but are read-only in user-facing edit flows.
- Deleted reminders are hidden from normal app views.
- Admin can use `all_objects` or the existing soft-delete admin pattern to inspect deleted records.

Add a focused queryset/manager with methods such as:

- `for_user(user)`: reminders owned by the given user.
- `active()`: not completed and not deleted.
- `completed()`: completed and not deleted.
- `overdue(today)`: not completed, not deleted, date before today.
- `not_overdue(today)`: active reminders with no date or date today/future.
- `urgent_first()`: stable ordering with urgent records first.

## Home Visibility Rules

Home reminders are always scoped to `request.user` and exclude completed or deleted reminders.

The home page should split reminders into two groups.

### Recordatorios Para Hoy

Show reminders that match any of these conditions:

- No `reminder_date` and no `client`: shown every day until marked `LISTO`.
- `reminder_date == today`: shown only on that exact date.
- No `reminder_date` and `client` is in the logged-in user's assigned route for today.

### Recordatorios De Clientes En Ruta

Show lower-priority route-context reminders when:

- `client` is in the logged-in user's assigned route for today.
- `reminder_date` is in the future.

This keeps date priority intact: a future-dated client reminder is not promoted to a main today alert just because the client is in today's route. It is still visible as route context, and the user may mark it `LISTO` at any time.

Past-dated incomplete reminders do not appear on the home page. They are available through the `Vencidos` filter on the `Recordatorios` page.

Ordering:

- Urgent reminders appear first and receive stronger visual treatment.
- In the today group, today-dated reminders come before route/no-date reminders and general no-date reminders.
- In the future route group, nearest future dates come first after urgent priority.

## Route Matching

Route-based visibility should reuse the existing route ownership behavior from `routes.views.today_route`.

For the logged-in user:

1. Resolve `request.user.employee`.
2. Find active `core.Transport` where `assigned_driver` is that employee.
3. Find today's active route for that transport through `Route.get_today_routes(transportation=transportation)`.
4. Use the first today route, matching existing behavior.
5. Resolve due clients with `RouteClient.objects.due_on(today).filter(route=today_route)`.
6. Match reminders whose `client_id` is in that due-client set.

If the user has no employee, no active transport, or no route today, route-based reminder groups are empty. Date-based and no-date/no-client reminders still work.

## Pages And Actions

Use a new app namespace, `reminders`, with Spanish routes and labels in the UI.

### Recordatorios List

`GET /recordatorios/`

Default list:

- current user's active reminders
- includes future-dated reminders and no-date reminders
- excludes completed, deleted, and past-dated incomplete reminders

Filters:

- `Activos`: default active future/no-date reminders.
- `Vencidos`: incomplete reminders whose `reminder_date` is before today.
- `Listos`: completed reminders.

Additional controls:

- Search by title and description.
- Filter by client.
- Client names link to client detail.
- Urgent reminders sort first and render highlighted.

### Create Reminder

`GET/POST /recordatorios/nuevo/`

Fields:

- title
- description
- client
- reminder date
- urgent

Behavior:

- Dedicated page, not a modal.
- Optional `?client=<id>` preselects the client.
- If the create request comes from client detail, the form opens with that client preselected.
- After successful save, redirect to home.

### Edit Reminder

`GET/POST /recordatorios/<id>/editar/`

Behavior:

- Owner-only in user-facing views.
- Completed reminders are read-only and cannot be edited.
- After successful save, redirect to home.

### Complete Reminder

`POST /recordatorios/<id>/listo/`

Behavior:

- Owner-only in user-facing views.
- Sets `completed_at` and `completed_by`.
- Available from home, route-context reminder group, and list page.
- Safe to call once; repeat calls should not corrupt completion metadata.

### Delete Reminder

`POST /recordatorios/<id>/eliminar/`

Behavior:

- Owner-only in user-facing views.
- Soft-deletes via `deleted_at`.
- This is distinct from `LISTO`.
- Deleted reminders are not shown in normal user filters.

## Navigation And UI Placement

Add:

- Header/navigation button: `NUEVO RECORDATORIO`.
- Header/navigation link: `Recordatorios`.
- Client detail action: `NUEVO RECORDATORIO`.

Home integration:

- Render a reusable reminder block near the top of the dashboard before existing main cards/metrics.
- Include the block in the relevant authenticated home templates:
  - `core/templates/home.html`
  - `core/templates/delivery_dashboard.html`
  - `core/templates/manager_dashboard.html`
- Anonymous users see no reminder block.

Reminder cards/rows should show:

- title
- optional description
- optional linked client
- optional date
- urgent visual highlight when `urgent=True`
- `LISTO` action when the reminder is not completed
- edit/delete actions where appropriate

## Services And View Boundaries

Add a small reminder service layer because visibility combines reminder ownership, dates, route membership, and dashboard grouping.

Suggested service functions:

- `get_home_reminder_context(user, today=None)`: returns `today_reminders` and `route_context_reminders`.
- `get_user_route_client_ids(user, today=None)`: returns due route client IDs using the existing route ownership model.
- `complete_reminder(reminder, user)`: validates ownership and sets completion metadata.
- `soft_delete_reminder(reminder, user)`: validates ownership and soft-deletes.

Views should stay thin and use model/queryset/service methods for core behavior. This matches the repository convention that orchestration and multi-model coordination belong in services.

## Admin

Register `Reminder` in Django admin.

Admin behavior:

- Superusers/admins can see the full reminder list without owner restriction.
- Show owner, client, date, urgent, completion state, completed by, created date, and deleted state.
- Provide filters for urgent, completed, date, owner, and client.
- Use the existing soft-delete admin pattern where appropriate.

## Error Handling And Edge Cases

- Anonymous users are redirected to login for reminder views.
- A normal user cannot view, edit, complete, or delete another user's reminder.
- Completing an already completed reminder should be idempotent or return a harmless success without changing the original completion metadata.
- Editing a completed reminder from user-facing views should be rejected or redirected with a clear message.
- A missing or invalid `?client=<id>` preselection should render the create form without a selected client rather than failing.
- If a route lookup fails because the user has no employee/transport/today route, home still renders date and no-date reminders.

## Test Plan

Model/queryset tests:

- Active reminders exclude completed and deleted records.
- `Vencidos` finds incomplete past-dated reminders.
- `Listos` finds completed non-deleted reminders.
- User scoping returns only reminders created by that user.
- Urgent reminders sort before normal reminders.

Home visibility tests:

- No-date/no-client reminders appear on home until completed.
- Today-dated reminders appear on home.
- Future-dated reminders do not appear in the main today group.
- Past-dated incomplete reminders do not appear on home.
- Client-only reminders appear when the client is in the user's assigned route today.
- Future-dated client reminders in today's route appear in the lower-priority route context group.
- Route-based visibility is empty when the user has no employee, transport, or route today.

View/action tests:

- Create requires authentication.
- Create saves `created_by`.
- Create with `?client=<id>` preselects the client.
- Successful create redirects home.
- Edit is owner-only.
- Completed reminders cannot be edited from user-facing views.
- `LISTO` is owner-only and sets `completed_at` and `completed_by`.
- `Eliminar` is owner-only and sets `deleted_at`.
- Another user cannot view, edit, complete, or delete someone else's reminder.
- List filters show `Activos`, `Vencidos`, and `Listos` correctly.
- Search by title/description filters results.
- Client filter limits results to the selected client.

Admin tests can be minimal unless existing admin conventions require coverage.

## Implementation Notes

- Add `reminders` to `INSTALLED_APPS`.
- Add `path('recordatorios/', include('reminders.urls'))` to project URLs.
- Use Spanish labels in templates and forms, while keeping code identifiers in English.
- Prefer shared partial templates for reminder cards/rows so the home block and list page stay consistent.
- Use `timezone.localdate()` for date comparisons.
- Keep date comparisons date-only; do not introduce time-of-day behavior.
- Keep this separate from the existing `notification` app to avoid mixing personal task reminders with outbound notification delivery.
