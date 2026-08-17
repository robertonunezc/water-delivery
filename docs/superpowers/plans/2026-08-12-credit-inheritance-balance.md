# Credit Inheritance Balance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make branch credit orders consume corporate credit unless the branch has `credit_override_enabled=True`.

**Architecture:** Add a model-level resolver that returns the client whose credit ledger applies to a sale. Use that resolver in credit validations, debt mutations, settlement, and credit-order reporting while keeping orders and payments attached to the ordering branch.

**Tech Stack:** Django 5.2, django-tenants test case helpers, PostgreSQL-backed Django tests.

## Global Constraints

- No schema changes.
- No historical credit transaction migration.
- Preserve existing payment/order ownership: `Order.client` and `Payment.client` stay as the ordering client.
- All new functions and changed service signatures need explicit type hints.
- Use service/model logic, not view-level business rules.

---

### Task 1: Effective Credit Account

**Files:**
- Modify: `clients/models.py`
- Test: `payment/tests.py`

**Interfaces:**
- Produces: `Client.get_credit_account(self) -> "Client"`
- Produces: `Client.get_effective_credit_config(self) -> Optional["ClientCreditConfig"]`
- Produces: `Client.get_available_credit(self) -> Decimal`
- Consumes: existing `Client.type`, `Client.corporate_id`, `Client.corporate`, `Client.credit_override_enabled`

- [x] **Step 1: Write failing tests for credit account resolution**

Update the test import in `payment/tests.py` to include `CreditTransaction`. Add tests to `CreditOrderRegistrationRuleTests`:

```python
def test_branch_without_credit_override_resolves_corporate_credit_account(self):
    corporate = Client.objects.create(name='Corporativo cuenta crédito', type='corporate')
    branch = Client.objects.create(
        name='Sucursal hereda cuenta crédito',
        type='branch',
        corporate=corporate,
        credit_override_enabled=False,
    )

    self.assertEqual(branch.get_credit_account(), corporate)

def test_branch_with_credit_override_resolves_own_credit_account(self):
    corporate = Client.objects.create(name='Corporativo no usado', type='corporate')
    branch = Client.objects.create(
        name='Sucursal crédito propio',
        type='branch',
        corporate=corporate,
        credit_override_enabled=True,
    )

    self.assertEqual(branch.get_credit_account(), branch)
```

- [x] **Step 2: Run tests and verify RED**

Run: `.venv/bin/python manage.py test payment.tests.CreditOrderRegistrationRuleTests --verbosity 1 --noinput`

Expected: fails with `AttributeError: 'Client' object has no attribute 'get_credit_account'`.

- [x] **Step 3: Implement resolver methods**

Add to `Client`:

```python
def get_credit_account(self) -> "Client":
    if self.type == 'branch' and self.corporate_id and not self.credit_override_enabled:
        return self.corporate
    return self

def get_effective_credit_config(self) -> Optional["ClientCreditConfig"]:
    try:
        return self.get_credit_account().credit_config
    except ObjectDoesNotExist:
        return None
```

Update `get_available_credit()`, `can_use_credit_for_payment()`, `validate_credit_payment()`, and `can_afford_order()` to calculate credit availability from `self.get_credit_account()` and return/use `Decimal` amounts.

- [x] **Step 4: Run tests and verify GREEN**

Run: `.venv/bin/python manage.py test payment.tests.CreditOrderRegistrationRuleTests --verbosity 1 --noinput`

Expected: resolver tests pass.

### Task 2: Credit Purchase And Settlement Ledgers

**Files:**
- Modify: `clients/models.py`
- Modify: `clients/services/balance_service.py`
- Modify: `payment/services.py`
- Test: `payment/tests.py`

**Interfaces:**
- Consumes: `Client.get_credit_account(self) -> "Client"`
- Produces: `balance_service.add_debt(client: Client, ...)` mutates the effective credit account for `transaction_type='purchase'`
- Produces: `balance_service.pay_debt(client: Client, ...)` reduces the effective credit account

- [x] **Step 1: Write failing tests for branch credit order registration**

Add tests to `CreditOrderRegistrationRuleTests`:

```python
def test_branch_credit_order_without_override_charges_corporate_credit(self):
    corporate = Client.objects.create(
        name='Corporativo crédito compartido',
        type='corporate',
        credit_limit=Decimal('1000.00'),
        current_debt=Decimal('0.00'),
        can_pay_with_credit=True,
    )
    branch = Client.objects.create(
        name='Sucursal crédito heredado',
        type='branch',
        corporate=corporate,
        credit_limit=Decimal('0.00'),
        current_debt=Decimal('0.00'),
        can_pay_with_credit=False,
        credit_override_enabled=False,
    )
    order = Order.objects.create(client=branch, total_amount=Decimal('500.00'), type='credito')

    response, status_code = services.process_payment_request(
        order=order,
        data=PaymentRequestData(),
        request_user=self.user,
    )

    self.assertEqual(status_code, 200)
    self.assertTrue(response['success'])
    corporate.refresh_from_db()
    branch.refresh_from_db()
    self.assertEqual(corporate.current_debt, Decimal('500.00'))
    self.assertEqual(branch.current_debt, Decimal('0.00'))
    self.assertEqual(corporate.get_available_credit(), Decimal('500.00'))
    self.assertTrue(
        CreditTransaction.objects.filter(
            client=corporate,
            reference_order=order,
            transaction_type='purchase',
            amount=Decimal('500.00'),
        ).exists()
    )

def test_branch_credit_order_without_override_uses_corporate_limit(self):
    corporate = Client.objects.create(
        name='Corporativo límite usado',
        type='corporate',
        credit_limit=Decimal('1000.00'),
        current_debt=Decimal('800.00'),
        can_pay_with_credit=True,
    )
    branch = Client.objects.create(
        name='Sucursal límite heredado',
        type='branch',
        corporate=corporate,
        credit_limit=Decimal('1000.00'),
        current_debt=Decimal('0.00'),
        can_pay_with_credit=True,
        credit_override_enabled=False,
    )
    order = Order.objects.create(client=branch, total_amount=Decimal('250.00'), type='credito')

    response, status_code = services.process_payment_request(
        order=order,
        data=PaymentRequestData(),
        request_user=self.user,
    )

    self.assertEqual(status_code, 400)
    self.assertIn('excede el límite de crédito', response['error'])
    corporate.refresh_from_db()
    branch.refresh_from_db()
    self.assertEqual(corporate.current_debt, Decimal('800.00'))
    self.assertEqual(branch.current_debt, Decimal('0.00'))

def test_branch_credit_order_with_override_charges_branch_credit(self):
    corporate = Client.objects.create(
        name='Corporativo crédito separado',
        type='corporate',
        credit_limit=Decimal('1000.00'),
        current_debt=Decimal('200.00'),
        can_pay_with_credit=True,
    )
    branch = Client.objects.create(
        name='Sucursal crédito propio',
        type='branch',
        corporate=corporate,
        credit_limit=Decimal('600.00'),
        current_debt=Decimal('0.00'),
        can_pay_with_credit=True,
        credit_override_enabled=True,
    )
    order = Order.objects.create(client=branch, total_amount=Decimal('500.00'), type='credito')

    response, status_code = services.process_payment_request(
        order=order,
        data=PaymentRequestData(),
        request_user=self.user,
    )

    self.assertEqual(status_code, 200)
    corporate.refresh_from_db()
    branch.refresh_from_db()
    self.assertEqual(corporate.current_debt, Decimal('200.00'))
    self.assertEqual(branch.current_debt, Decimal('500.00'))
```

- [x] **Step 2: Run tests and verify RED**

Run: `.venv/bin/python manage.py test payment.tests.CreditOrderRegistrationRuleTests --verbosity 1 --noinput`

Expected: tests fail because branch credit state is used directly.

- [x] **Step 3: Implement effective-account debt mutations**

Update `balance_service.add_debt()` and `balance_service.pay_debt()` to resolve `credit_account = client.get_credit_account()`, lock that account, validate against that account, mutate that account, and create `CreditTransaction(client=locked_client, ...)`.

- [x] **Step 4: Update payment registration and settlement queries**

In `payment/services.py`:

```python
credit_account = order.client.get_credit_account()
existing_purchase = credit_account.credit_transactions.filter(
    reference_order=order,
    transaction_type='purchase',
).first()
```

Use `order.client.get_credit_account()` for `_reconcile_unapplied_credit_payment()` accounted-payment lookup. Keep pending-credit `Payment.client` as `order.client`.

- [x] **Step 5: Run tests and verify GREEN**

Run: `.venv/bin/python manage.py test payment.tests.CreditOrderRegistrationRuleTests payment.tests.CreditOrderSettlementTests --verbosity 1 --noinput`

Expected: all registration and settlement tests pass.

### Task 3: Order Service Credit Helper

**Files:**
- Modify: `orders/services.py`
- Test: `orders/tests.py`

**Interfaces:**
- Consumes: `Client.get_credit_account(self) -> "Client"`
- Produces: `process_order_payment(...)` validates and reports credit state from the effective credit account.

- [x] **Step 1: Write failing test for legacy order payment helper**

Add to `ProcessOrderPaymentTestCase`:

```python
def test_process_order_payment_branch_without_override_uses_corporate_credit(self) -> None:
    corporate = Client.objects.create(
        name='Corporativo helper crédito',
        type='corporate',
        credit_limit=Decimal('1000.00'),
        current_debt=Decimal('0.00'),
        can_pay_with_credit=True,
    )
    branch = Client.objects.create(
        name='Sucursal helper crédito',
        type='branch',
        corporate=corporate,
        balance=Decimal('0.00'),
        credit_limit=Decimal('0.00'),
        current_debt=Decimal('0.00'),
        can_pay_with_credit=False,
        credit_override_enabled=False,
    )
    order = Order.objects.create(client=branch, total_amount=Decimal('500.00'))

    result = services.process_order_payment(
        client=branch,
        order_amount=Decimal('500.00'),
        payment_method='credit',
        order=order,
    )

    self.assertTrue(result['success'])
    corporate.refresh_from_db()
    branch.refresh_from_db()
    self.assertEqual(corporate.current_debt, Decimal('500.00'))
    self.assertEqual(branch.current_debt, Decimal('0.00'))
    self.assertEqual(result['current_debt'], Decimal('500.00'))
```

- [x] **Step 2: Run test and verify RED**

Run: `.venv/bin/python manage.py test orders.tests.ProcessOrderPaymentTestCase --verbosity 1 --noinput`

Expected: the new test fails because `process_order_payment()` checks the branch credit toggle/limit.

- [x] **Step 3: Implement effective-account validation**

Inside `process_order_payment()`, resolve `credit_account = client.get_credit_account()` once. Use branch `client.balance` for balance payments, and use `credit_account.can_pay_with_credit`, `credit_account.credit_limit`, and `credit_account.current_debt` for credit validation and response fields.

- [x] **Step 4: Run tests and verify GREEN**

Run: `.venv/bin/python manage.py test orders.tests.ProcessOrderPaymentTestCase --verbosity 1 --noinput`

Expected: all order payment helper tests pass.

### Task 4: Pending Credit And Reports

**Files:**
- Modify: `clients/services/pending_payment_service.py`
- Modify: `clients/services/credit_report_service.py`
- Test: `payment/tests.py`
- Test: `clients/tests/tests_credit_report_service.py`

**Interfaces:**
- Consumes: `Client.get_credit_account(self) -> "Client"`
- Consumes: `Client.get_effective_credit_config(self) -> Optional["ClientCreditConfig"]`
- Produces: pending-credit helpers find branch orders whose credit transaction belongs to the corporate account.

- [x] **Step 1: Write failing overdue test for branch inherited credit**

Add to `CreditOrderRegistrationRuleTests`:

```python
def test_branch_without_override_overdue_lookup_uses_corporate_credit_config(self):
    corporate = Client.objects.create(
        name='Corporativo vencimiento heredado',
        type='corporate',
        credit_limit=Decimal('1000.00'),
        can_pay_with_credit=True,
    )
    ClientCreditConfig.objects.create(
        client=corporate,
        payment_term_type='monthly_cutoff',
        cutoff_day='last_day',
    )
    branch = Client.objects.create(
        name='Sucursal vencimiento heredado',
        type='branch',
        corporate=corporate,
        credit_override_enabled=False,
    )
    order = Order.objects.create(client=branch, total_amount=Decimal('100.00'), type='credito')
    balance_service.add_debt(
        client=branch,
        amount=Decimal('100.00'),
        transaction_type='purchase',
        reference_order=order,
    )
    Order.objects.filter(pk=order.pk).update(order_date=timezone.now() - timedelta(days=60))

    self.assertTrue(client_has_overdue_credit(branch))
```

- [x] **Step 2: Run test and verify RED**

Run: `.venv/bin/python manage.py test payment.tests.CreditOrderRegistrationRuleTests --verbosity 1 --noinput`

Expected: the new overdue assertion fails before pending lookup changes.

- [x] **Step 3: Implement inherited pending lookup**

In `pending_payment_service.py`, resolve the credit account for the requested client. Query purchase transactions by the credit account. If the requested client differs from the credit account, filter transactions to `reference_order__client=client`. Use `order.client.get_effective_credit_config()` when calculating due dates.

- [x] **Step 4: Update credit report lookup**

In `credit_report_service.py`, derive open credit orders from purchase transaction references, not from `Order.client_id == CreditTransaction.client_id`. Use `order.client.get_effective_credit_config()` for due dates so branch orders inherit corporate terms.

- [x] **Step 5: Run focused tests**

Run: `.venv/bin/python manage.py test payment.tests.CreditOrderRegistrationRuleTests payment.tests.CreditOrderSettlementTests orders.tests.ProcessOrderPaymentTestCase orders.tests.CancelOrderServiceTestCase --verbosity 1 --noinput`

Expected: all focused tests pass.

### Task 5: Final Verification

**Files:**
- Verify only.

**Interfaces:**
- Consumes all prior tasks.

- [x] **Step 1: Run focused regression suite**

Run: `.venv/bin/python manage.py test payment.tests.CreditOrderRegistrationRuleTests payment.tests.CreditOrderSettlementTests orders.tests.ProcessOrderPaymentTestCase orders.tests.CancelOrderServiceTestCase --verbosity 1 --noinput`

Expected: all tests pass.

- [x] **Step 2: Run broader tests for touched apps**

Run: `.venv/bin/python manage.py test payment orders clients --verbosity 1 --noinput`

Expected: all tests pass or any failure is reported with exact traceback and scope.

- [x] **Step 3: Review diff**

Run: `git diff --stat` and `git diff --check`

Expected: scoped files only and no whitespace errors.
