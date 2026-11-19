# Branch Credit Transfer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move unpaid branch credit debt atomically when its credit account changes.

**Architecture:** Persist the current debt account and original credit terms on
orders. Preserve historical sales/payments and record paired transfer entries.
Centralize transfer orchestration and current-account queries for all consumers.

**Tech Stack:** Django 5.2, PostgreSQL, django-tenants, unittest/pytest.

**Spec:** `docs/superpowers/specs/2026-11-04-branch-credit-transfer-design.md`

## Global Constraints

- Transfer only unpaid credit balances; retain history and original deadlines.
- Independent account limits; destination debt must fit or everything rolls back.
- Both directions use the same atomic service; no automatic legacy debt migration.
- Typed functions; managers/querysets for queries, services for transactions.

## Review Focus

- Partial payments before/after transfer and cancellation must leave both ledgers balanced.
- Repeated switches and repeated migration runs must not duplicate debt.
- Reports and overdue checks must not count old purchase owners after a transfer.
- A switch submitted through the basic edit form or Django admin must use the service.
- Legacy orders without an invoice must retain their invoice-relative credit terms.

### Task 1: Transfer and credit ownership

**Files:** `clients/models.py`, `clients/managers.py`,
`clients/services/credit_transfer_service.py`, `clients/services/client_service.py`,
`clients/services/balance_service.py`, `orders/models.py`, app migrations,
`clients/test_credit_transfers.py`.

**Interfaces:** Produces `transfer_branch_credit(branch, source, target, user) -> Decimal`,
`Order.get_credit_account()`, `Order.get_effective_credit_config()` and
`OrderQuerySet.for_credit_accounts(account_ids)`.

- [x] Write and run a failing MXN 5,000 / 4,000 / 2,000 switch test.
- [x] Add current-account/terms fields and append-only transfer ledger records.
- [x] Implement capacity validation and atomic forward/reverse switches.
- [x] Add and run partial-payment, insufficient-capacity, repeat-switch and history tests.

### Task 2: Consumers and original deadlines

**Files:** `payment/services.py`, `orders/services/__init__.py`,
`orders/services/order_split_service.py`, `clients/services/credit_report_service.py`,
`clients/services/pending_payment_service.py`, `clients/services/credit_payment_service.py`,
`clients/services/credit_reconciliation_service.py`, integration tests.

**Interfaces:** Consumes Task 1's order ownership and credit terms API.

- [x] Add failing settlement/report/overdue/cancellation/split tests after transfer.
- [x] Route payments, order queries and reversals through current debt ownership.
- [x] Snapshot terms when credit is charged or legacy debt is transferred; copy on split.
- [x] Verify payment history remains intact and corporate/branch reports reconcile.

### Task 3: Edit surfaces and explicit legacy migration

**Files:** `clients/forms.py`, `clients/admin.py`, `clients/views.py`,
`clients/management/commands/transfer_branch_credit.py`, tests, operator docs.

**Interfaces:** Consumes `update_client()` and Task 1's transfer service.

- [x] Add failing form/admin and command preview/apply/insufficient-limit tests.
- [x] Route account changes through the service and display validation failures.
- [x] Add tenant-scoped command with preview default, explicit apply and branch selector.
- [x] Document deployment migrations and legacy preview/apply commands.

### Task 4: Verification and review

- [x] Run relevant clients/orders/payment/invoice tests, full suite, Django checks and migration drift checks.
- [x] Review the final diff against the spec and repository standards with fresh agents.
- [x] Fix material findings with regression tests, record outcomes and commit on the requested branch.

## Execution record

- Starting commit: `3d7db6e146ae0dbabdb49afe1202c1ac56e87971`.
- `git switch main` and `git pull --ff-only origin main`: completed, already current.
- Baseline `manage.py test clients.test_credit_management`: 23 tests passed.
- User authorized implementation of all six recommendations; no further design approval is pending.
- Final targeted transfer suite: 24 tests passed.
- A real two-connection PostgreSQL test reproduced the corporate-policy/branch-switch
  deadlock, then passed after consistent branch-before-account locking. Batch
  cancellation/migration, split entry points and invoice linking use the same order.
- Independent behavior and standards reviews found stale destination-limit,
  reconciliation, locking and branch-creation issues; all were addressed. No
  material findings or deferred minor issues remain.
- Final `.venv/bin/python -m pytest -q --reuse-db . clients/tests/tests_credit_terms.py clients/tests/tests_credit_report_service.py`:
  **341 passed, 21 subtests passed**. Existing dependency/static-file warnings remain.
- `manage.py check`: no issues. `makemigrations --check --dry-run`: no changes.
- `compileall` and `git diff --check`: passed.
- Deployment and existing-branch migration steps are in `docs/branch-credit-transfers.md`.
  No live debt migration, push or deployment was performed.
