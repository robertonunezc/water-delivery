# CODEX.md

Guidance for Codex when working in this repository.

## Project Overview

This is a Django 5.2 monolith for a water delivery business in a Spanish/Mexico
locale. It uses `django-tenants`: tenant/domain management lives in the public
schema, while business data lives in tenant schemas.

Core business apps:

- `clients` - clients, corporate/branch relationships, addresses, fiscal data,
  balances, credit configuration, and credit/balance ledgers.
- `orders` - sales orders, order items, cancellation review, receipts, and
  receipt delivery.
- `payment` - payments and accounting side effects for balance payments.
- `invoice` - billing/invoice records, invoice schedules, invoice/order links.
  The URL path still uses `billing/`, and some database table names keep the
  old `billing_*` names for compatibility.
- `routes` - route assignments, scheduled visits, route order links, truck
  inventory reconciliation.
- `route_confirmations` - visit confirmation links/messages.
- `product` - products, categories, and client-specific prices.
- `reminders` - user/client reminders.
- `notification` - notification records and channel stubs.
- `report` - report views.
- `tenant_client` - public-schema tenant/domain models and admin.
- `core` - shared models, admin mixins, middleware, dashboard/services, health
  checks, employees, transports, non-working days.

## Commands

Use the virtual environment before running project commands:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Common commands:

```bash
make migrate            # makemigrations + migrate
python manage.py migrate
make runserver          # runserver 0.0.0.0:8002
make test               # python manage.py test
python manage.py test core -q
make format             # black + isort
make lint               # flake8 + pylint
make shell
make celery-worker
make celery-beat
```

`pytest.ini` is present for pytest-django, but the canonical test command in
the Makefile is `python manage.py test`.

## Settings And Infrastructure

- Base settings are in `water_delivery/settings.py`; development and production
  overrides live in `settings_development.py` and `settings_production.py`.
- `.env` is loaded with `python-dotenv`.
- Database uses `django_tenants.postgresql_backend` and `POSTGRES_*` variables.
- Redis powers Celery broker/result backend. Redis URLs can be overridden with
  `REDIS_BROKER_URL` and `REDIS_RESULT_BACKEND`.
- `ROOT_URLCONF = water_delivery.tenant_urls`; public schema URLs come from
  `water_delivery.public_urls`.
- Public URLs expose tenant/domain admin and health checks. Tenant URLs expose
  the business app routes and tenant admin.
- Celery is configured in `water_delivery/celery.py`, with tenant helpers
  `tenant_task_wrapper` and `run_for_all_tenants`.
- Monthly invoice schedule population is configured in
  `water_delivery/celery_schedule.py`.
- Docker files: `docker-compose.dev.yml`, `docker-compose.prod.yml`,
  `Dockerfile`, and `nginx.conf`.

## Architecture Patterns

### Soft Delete

`core.models.TimeStampedModel` provides:

- `created_at`
- `updated_at`
- `deleted_at`
- `objects` - default manager excluding soft-deleted rows
- `all_objects` - includes soft-deleted rows

`delete()` sets `deleted_at` instead of deleting the row. Do not assume
`Model.objects` returns historical or deleted records. Use `all_objects` only
when the feature explicitly needs them.

Some apps define their own managers/querysets on top of this pattern:

- `orders.models.OrderManager` filters `deleted_at=None` and exposes filters
  like `active()`, `cancelled()`, `unbilled()`, `paid()`, and `unpaid()`.
- `routes.models.RouteClientManager` filters soft-deleted route clients and
  exposes route-specific queryset helpers.
- `payment.models.PaymentManager` filters soft-deleted payments.
- `product.models.ProductManager` returns active, non-deleted products by
  default. Use `include_inactive()` or `all_objects` deliberately.
- `reminders.models.ReminderManager` filters soft-deleted reminders.

Admin classes that support soft deletion should use
`core.admin_mixins.SoftDeleteAdminMixin`, which replaces Django's bulk delete
action with soft delete behavior.

### Models, Managers, And Services

Use the local pattern already present in the repo:

- Put entity-local state checks and invariants on the model or a custom
  queryset/manager.
- Put orchestration that spans models, needs transactions, calls external
  services, or coordinates side effects in `services.py`.
- Views and Django admin actions should call models/managers/services; do not
  put domain workflows inline in views or admin methods.
- Wrap multi-table all-or-nothing workflows in `transaction.atomic()`.
- Use `select_for_update()` when a workflow mutates financial, invoice, or
  inventory state that could be changed concurrently.
- Services should have explicit type hints and focused unit tests.

Models should not start/commit transactions, call external APIs, schedule
background jobs, perform permission logic, or coordinate unrelated aggregates.

## Business Rules And Sharp Edges

### Clients, Balance, And Credit

`clients.models.Client` owns the core customer fields and corporate/branch
relationship:

- `type` is `corporate` or `branch`.
- Branch clients normally require `corporate`.
- Branches do not inherit delivery addresses for order eligibility.
- Credit may be inherited from the corporate account unless
  `credit_override_enabled` is enabled.

Balance and credit ledgers:

- `BalanceTransaction` records deposits, balance payments, refunds, transfers,
  corrections, and reversals.
- `CreditTransaction` records credit purchases, debt payments, reversals,
  adjustments, interest/fees, forgiveness, and limit changes.
- Use `clients.services.balance_service` and related client services for
  balance/credit mutations instead of manually editing `balance`,
  `current_debt`, or ledger rows.

### Payments

`payment.models.Payment.save()` applies accounting side effects by default for
new completed balance payments. Service code sometimes calls
`payment.save(apply_accounting=False)` and then applies side effects explicitly
inside a transaction. Preserve that distinction.

Payment workflows live in `payment/services.py`. This service validates selected
orders, locks rows for client order payment, settles pending credit payments,
creates payment rows, and adds overpayment to client balance.

### Orders

Orders use `OrderStatus` values `PENDING`, `COMPLETED`, and `CANCELLED`.
`Order.total_paid` ignores `pending_credit` payments and counts completed
payments only. `Order.is_closed` means completed and fully paid.

Order receipt creation lives under `orders/services/receipt_*`. Receipt
services generate PDFs, upload storage, choose delivery channel, and send via
email/WhatsApp abstractions. They use tenant context from `connection.tenant`.

### Invoices

The app is named `invoice`, but many user-facing concepts and legacy database
tables still use billing names.

`invoice.models.Invoice` protects issued invoice fields:

- Immutable fields cannot be edited once the invoice is no longer a draft.
- Deleting an invoice raises `ValidationError`; cancellation should use
  `invoice.services.cancel_invoice()`.
- `InvoiceStatus` values are `DRAFT`, `ACTIVE`, and `CANCELLED`.

Invoice/order linking and fiscal owner validation belong in `invoice/services.py`.
Corporate/branch fiscal ownership rules are handled there.

### Routes And Inventory

Route assignment logic is in `routes.models.RouteClient` and
`routes/services.py`.

- `RouteClient.is_due_on()` calculates recurring visits from `anchor_date`,
  `interval_weeks`, and route weekday.
- Saving a route client aligns `anchor_date` to the route weekday and validates
  delivery address requirements.
- Truck inventory reconciliation is handled by route services. Completed order
  payments can trigger inventory session synchronization through payment
  services.

### Tenants And Background Jobs

Tenant models live in `tenant_client.models.ClientTenant` and `Domain`.
`ClientTenant.auto_create_schema = True`.

When adding background jobs that touch tenant business data, run them inside the
correct tenant schema. Prefer the existing Celery helpers:

- `water_delivery.celery.tenant_task_wrapper`
- `water_delivery.celery.run_for_all_tenants`

Do not write background tasks that query tenant models from the public schema
by accident.

### Employee And User Handling

The app uses Django's built-in `auth.User`; do not change `AUTH_USER_MODEL`
without a migration plan.

`core.models.Employee.user` is nullable. Employees can exist without system
access. `core.admin.EmployeeAdmin.save_model()` creates a user with an unusable
password when saving an employee without a linked user. `core/signals.py` is
intentionally disabled; do not re-enable automatic employee creation without
reviewing the admin workflow.

## Frontend And Admin Conventions

- Admin uses `django-unfold` and `crispy_forms` with the Unfold crispy template
  pack.
- Keep admin customizations in the relevant app `admin.py`.
- Custom admin list/form templates are present under app `templates/admin/...`
  and root `templates/admin/...`.
- JavaScript should be written in an object-oriented style: encapsulate state
  and behavior in classes, avoid globals, and keep admin/frontend scripts
  modular.
- Static files are under each app's `static/` directory.

## Code Style

- Add type hints to all function signatures.
- Use f-strings for string formatting.
- Use `logging.getLogger(__name__)` for logging.
- Keep functions focused, generally under 20-30 lines. Extract helpers when a
  workflow grows.
- Prefer structured model/queryset/service APIs over ad hoc queries spread
  through views.
- Keep Spanish domain/user-facing text consistent with the existing codebase.
- Preserve legacy database table names and backwards-compatible aliases unless
  a migration plan explicitly says otherwise.

## Testing Guidance

- Use `python manage.py test` or `make test` for the default suite.
- Run app-scoped tests for focused changes, for example:

```bash
python manage.py test clients -q
python manage.py test orders -q
python manage.py test invoice -q
python manage.py test routes -q
```

- Financial flows need tests around balance/credit transactions, payments,
  invoice links, and reversals.
- Tenant-aware code should be tested with tenant context or the utilities under
  `tenant_client/test_utils.py`.
- Soft-delete behavior should test both `objects` and `all_objects` when the
  feature depends on historical records.

## Files To Inspect First

- `water_delivery/settings.py` - tenant app split, DB, Redis, Celery, middleware.
- `water_delivery/tenant_urls.py` and `water_delivery/public_urls.py` - URL
  boundaries between public and tenant schemas.
- `core/models.py` - soft delete, employees, transports, non-working days.
- `core/admin.py` and `core/admin_mixins.py` - admin conventions and employee
  user creation.
- `clients/models.py` and `clients/services/` - clients, balance/credit,
  corporate/branch rules, billing/fiscal helpers.
- `payment/models.py` and `payment/services.py` - payment side effects and
  order payment orchestration.
- `orders/models.py` and `orders/services/` - order state, receipts, delivery.
- `invoice/models.py` and `invoice/services.py` - invoice immutability,
  schedules, fiscal ownership, invoice/order links.
- `routes/models.py` and `routes/services.py` - routes, recurring visits,
  inventory sessions.
- `tenant_client/` - tenant/domain management and public admin.
- `docs/superpowers/specs/` and `docs/superpowers/plans/` - prior feature
  design and implementation plans.

## High-Risk Changes

Be extra careful with:

- Changing soft-delete managers or replacing `objects` behavior.
- Editing balance, credit, payment, invoice, or inventory side effects.
- Editing invoice immutability/cancellation behavior.
- Adding tasks without tenant schema context.
- Re-enabling signals.
- Changing Django auth user behavior.
- Renaming the `invoice` app or legacy `billing_*` database tables.
- Updating admin workflows that create users, mutate payments, or perform bulk
  deletes.

