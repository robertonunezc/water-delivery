# Route Visit Confirmations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add route visit confirmations so employees can email one-click confirmation links for a client's next due route visit.

**Architecture:** Create a focused `route_confirmations` tenant app that owns confirmation data, token handling, channel-agnostic send services, public response views, and the management page. Integrate routes through small service calls and template context only.

**Tech Stack:** Django 5.2, django-tenants, PostgreSQL, existing Mailgun-backed `notification.channels.email.SendEmail`, Django templates.

**Spec:** `docs/superpowers/specs/2026-09-29-route-visit-confirmations-design.md`

## Global Constraints

- New app name is `route_confirmations`.
- Confirmation records are tenant data and must be added to `TENANT_APPS`.
- Stored statuses are exactly `Enviada`, `Confirmada`, and `NO visitar`.
- Expired pending records store `Enviada` but display as `Expirada`.
- One active confirmation per `RouteClient + visit_date`.
- Send target is the next due visit date, including today when due today.
- Email recipients come from all `Contact.email` values for the client.
- Sending is synchronous for v1.
- A send counts as successful when at least one recipient sends successfully.
- Resend is allowed only after expiration and reuses the same record.
- Public links use the same tenant domain and one shared token with action in the URL.
- Token remains reusable until a valid response is recorded.
- Staff/admin overrides require a note.
- Keep automated tests minimal: essential model/service/security paths only, no UI/view tests unless strictly necessary.

## Review Focus

- Route clients with no contact emails should not create a misleading sent state.
- Partial email failure should still persist a sent confirmation when at least one recipient succeeds.
- Expired resend must replace the token so old email links no longer work.
- Race-prone public response clicks should not change an already answered confirmation.
- Manual overrides must not allow an empty note.

---

### Task 1: Confirmation App And Model

**Files:**
- Create: `route_confirmations/__init__.py`
- Create: `route_confirmations/apps.py`
- Create: `route_confirmations/models.py`
- Create: `route_confirmations/migrations/__init__.py`
- Modify: `water_delivery/settings.py`
- Modify: `routes/models.py`
- Test: `route_confirmations/tests.py`

**Interfaces:**
- Produces: `VisitConfirmation` model.
- Produces: `VisitConfirmation.Status` choices with `SENT = 'Enviada'`, `CONFIRMED = 'Confirmada'`, `DO_NOT_VISIT = 'NO visitar'`.
- Produces: `VisitConfirmation.generate_token() -> str`.
- Produces: `VisitConfirmation.is_expired(reference_time: datetime | None = None) -> bool`.
- Produces: `VisitConfirmation.display_status(reference_time: datetime | None = None) -> str`.
- Produces: `VisitConfirmation.can_resend(reference_time: datetime | None = None) -> bool`.

- [ ] **Step 1: Write essential model tests**

Add tests for:
- active uniqueness by `route_client + visit_date`
- pending expired display status returns `Expirada`
- `RouteClient.delete()` soft-deletes related confirmations

- [ ] **Step 2: Run model tests to verify they fail**

Run: `.venv/bin/python manage.py test route_confirmations -v 1`
Expected: FAIL because the app/model do not exist.

- [ ] **Step 3: Create `route_confirmations` app and model**

Implement `VisitConfirmation(TimeStampedModel)` with fields from the spec, JSON `receipt_log`, token generation through `secrets.token_urlsafe(32)`, conditional unique constraint for active records, and indexes for route client, visit date, status, expiration, and token.

- [ ] **Step 4: Add tenant app and route-client archival hook**

Add `route_confirmations` to `TENANT_APPS`. In `RouteClient.delete()`, soft-delete active related confirmations before calling `super().delete()`.

- [ ] **Step 5: Create migration**

Run: `.venv/bin/python manage.py makemigrations route_confirmations`
Expected: migration file is created.

- [ ] **Step 6: Run model tests**

Run: `.venv/bin/python manage.py test route_confirmations -v 1`
Expected: PASS for Task 1 tests.

### Task 2: Core Confirmation Services

**Files:**
- Create: `route_confirmations/services.py`
- Modify: `route_confirmations/tests.py`

**Interfaces:**
- Consumes: `VisitConfirmation` from Task 1.
- Produces: `get_next_due_visit_date(route_client: RouteClient, today: date | None = None) -> date`.
- Produces: `get_or_create_confirmation(route_client: RouteClient, visit_date: date) -> VisitConfirmation`.
- Produces: `record_public_response(token: str, action: str, now: datetime | None = None) -> ResponseResult`.
- Produces: `override_confirmation(confirmation: VisitConfirmation, status: str, note: str, user: User) -> VisitConfirmation`.

- [ ] **Step 1: Write essential service tests**

Add tests for:
- next due date includes today when due today
- next due date skips to the next valid interval date when today is not due
- valid public `confirmar` records `Confirmada`
- valid public `no-visitar` records `NO visitar`
- expired public response records nothing
- already answered response keeps the first decision
- override without a note raises validation

- [ ] **Step 2: Run service tests to verify they fail**

Run: `.venv/bin/python manage.py test route_confirmations -v 1`
Expected: FAIL with missing service functions.

- [ ] **Step 3: Implement service result types and services**

Use small dataclasses for response results. Use `transaction.atomic()` and `select_for_update()` when recording responses and overrides.

- [ ] **Step 4: Run service tests**

Run: `.venv/bin/python manage.py test route_confirmations -v 1`
Expected: PASS for Tasks 1-2 tests.

### Task 3: Channel-Agnostic Sending

**Files:**
- Create: `route_confirmations/senders.py`
- Modify: `route_confirmations/services.py`
- Modify: `route_confirmations/tests.py`
- Create: `route_confirmations/templates/route_confirmations/email/visit_confirmation.txt`

**Interfaces:**
- Consumes: `get_next_due_visit_date()` and `get_or_create_confirmation()`.
- Produces: `SendReceipt(recipient: str, channel: str, success: bool, error: str = '')`.
- Produces: `BaseConfirmationSender.send(message: ConfirmationMessage) -> SendReceipt`.
- Produces: `ConfirmationSenderFactory.get_sender(channel: str) -> BaseConfirmationSender`.
- Produces: `send_visit_confirmation(route_client: RouteClient, sent_by: User, request: HttpRequest, channel: str = 'email') -> SendResult`.

- [ ] **Step 1: Write essential send tests**

Add tests with a fake sender for:
- all contact emails are attempted
- no contact emails returns a failed result and does not set `sent_at`
- partial send success sets `sent_at`, `expires_at`, token, and receipt log
- expired resend reuses the record and replaces token/receipt log
- pending non-expired resend is rejected

- [ ] **Step 2: Run send tests to verify they fail**

Run: `.venv/bin/python manage.py test route_confirmations -v 1`
Expected: FAIL with missing sender/service implementation.

- [ ] **Step 3: Implement sender interfaces and email sender**

Wrap `notification.channels.email.SendEmail`. Build absolute public action URLs from the incoming request. Format dates as `23 Febrero 2026`.

- [ ] **Step 4: Implement `send_visit_confirmation()`**

Collect non-empty `Contact.email`, create/reuse confirmation, enforce resend rules, reset token only for a new send/resend, call the sender for each recipient, persist receipt log, and count success if at least one receipt succeeds.

- [ ] **Step 5: Run send tests**

Run: `.venv/bin/python manage.py test route_confirmations -v 1`
Expected: PASS for Tasks 1-3 tests.

### Task 4: Views, URLs, And Route Integration

**Files:**
- Create: `route_confirmations/urls.py`
- Create: `route_confirmations/views.py`
- Create: `route_confirmations/forms.py`
- Create: `route_confirmations/templates/route_confirmations/confirmation_result.html`
- Create: `route_confirmations/templates/route_confirmations/list.html`
- Modify: `routes/services.py`
- Modify: `routes/templates/routes/route_detail.html`
- Modify: `core/templates/base.html`
- Modify: `water_delivery/urls.py`
- Modify: `water_delivery/tenant_urls.py`

**Interfaces:**
- Consumes: services from Tasks 2-3.
- Produces: `route_confirmations:respond` public URL.
- Produces: `/administrador/confirmaciones/` management list.
- Produces: route row badge/button state in route detail context.

- [ ] **Step 1: Implement forms**

Create a required-note override form with status choices for staff/admin manual overrides.

- [ ] **Step 2: Implement views and URLs**

Add authenticated send/list/override views and unauthenticated public response view. Keep employee mutations POST-only except public one-click response links.

- [ ] **Step 3: Integrate route detail context**

Annotate each route client payload with next visit confirmation state through a focused helper, then render badge and send/resend button in the existing route detail table.

- [ ] **Step 4: Add navigation and URL includes**

Add top-level `Confirmaciones` nav item and include app URLs in both root URLConfs.

- [ ] **Step 5: Run minimal app tests**

Run: `.venv/bin/python manage.py test route_confirmations -v 1`
Expected: PASS for essential service/model tests.

### Task 5: Verification And Cleanup

**Files:**
- Review all files changed in Tasks 1-4.

**Interfaces:**
- Consumes: completed implementation.
- Produces: final verified branch.

- [ ] **Step 1: Make migrations check**

Run: `.venv/bin/python manage.py makemigrations --check --dry-run`
Expected: `No changes detected`.

- [ ] **Step 2: Run focused test suites**

Run: `.venv/bin/python manage.py test route_confirmations routes -v 1`
Expected: PASS.

- [ ] **Step 3: Run Django checks**

Run: `.venv/bin/python manage.py check`
Expected: no issues.

- [ ] **Step 4: Review diff**

Run: `git diff --stat` and `git diff --check`
Expected: no whitespace errors; diff matches spec.
