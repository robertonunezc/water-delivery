# Client Detail Debt Display Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show client detail `Deuda actual` by client/order ownership while keeping inherited branch credit accounting on the corporate ledger.

**Architecture:** Add a focused helper in `clients.services.client_detail_service` that returns the debt value to display on the detail page. Regular clients, corporate clients, and override branches use their own `current_debt`; inherited branches compute net debt from credit transactions on the corporate account filtered by `reference_order__client`.

**Tech Stack:** Django 5.2, PostgreSQL, existing `Client`, `Order`, and `CreditTransaction` models.

## Global Constraints

- Keep accounting writes on the effective credit account; do not duplicate branch debt into `Client.current_debt`.
- Use existing service-layer patterns and typed function signatures.
- Add regression tests before production code.

---

### Task 1: Display Debt Helper

**Files:**
- Modify: `clients/services/client_detail_service.py`
- Test: `clients/tests.py`

**Interfaces:**
- Consumes: `Client.get_credit_account()`, `CreditTransaction.objects`, `CreditTransactionQuerySet.aggregate_summary()`
- Produces: `get_client_detail_current_debt(client: Client) -> Decimal`

- [ ] **Step 1: Write the failing tests**

Add tests to `ClientDetailSnapshotServiceTests` proving:
- An inherited branch shows net debt from corporate credit transactions tied to that branch's orders.
- Payments tied to the branch order reduce the branch's displayed debt.
- Corporate detail shows the corporate ledger debt, which is the sum of inherited branch debts.

- [ ] **Step 2: Run tests to verify RED**

Run: `.venv/bin/python manage.py test clients.tests.ClientDetailSnapshotServiceTests --verbosity 1 --noinput`

Expected: inherited branch debt test fails because `Deuda actual` is `$0.00`.

- [ ] **Step 3: Implement minimal helper and wire snapshot**

Add `get_client_detail_current_debt(client: Client) -> Decimal`. In `build_client_detail_snapshot`, use the helper for the `Deuda actual` card, and use the effective credit account for the credit limit shown in the credit card note.

- [ ] **Step 4: Update view percentage calculation**

In `clients/views.py`, compute `debt_percentage` from the display debt and effective credit account limit so inherited branch detail pages show correct credit usage.

- [ ] **Step 5: Run tests to verify GREEN**

Run: `.venv/bin/python manage.py test clients.tests.ClientDetailSnapshotServiceTests --verbosity 1 --noinput`

Expected: all snapshot service tests pass.

- [ ] **Step 6: Run focused regression suite**

Run: `.venv/bin/python manage.py test clients.tests.ClientDetailSnapshotServiceTests clients/tests --pattern=tests_credit_report_service.py payment.tests.CreditOrderRegistrationRuleTests payment.tests.CreditOrderSettlementTests orders.tests.ProcessOrderPaymentTestCase orders.tests.CancelOrderServiceTestCase --verbosity 1 --noinput`

Expected: all selected tests pass.
