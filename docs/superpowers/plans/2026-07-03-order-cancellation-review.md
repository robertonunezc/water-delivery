# Order Cancellation Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace pending-only deletion with status-based order cancellation, payment reversal, internal ledger reversal, and staff-visible cancellation review.

**Architecture:** Add cancellation review state to `Order`, a `reversed` payment status, and explicit reversal transaction types. Keep orchestration in `orders.services.cancel_order()`, using `transaction.atomic()` and row locks, while views/admin/templates delegate to the service.

**Tech Stack:** Django 5.2, django-tenants test cases, PostgreSQL, server-rendered templates, existing `clients` balance/credit ledger models.

---

## File Structure

- Modify `orders/models.py`: add query helpers and cancellation review fields.
- Modify `payment/models.py`: add `reversed` payment status.
- Modify `clients/models.py`: add balance/credit reversal transaction choices and validation direction rules.
- Modify `clients/managers.py`: include reversal transaction types in aggregate groups.
- Modify `clients/services/balance_service.py`: add small typed helpers for balance and credit reversal entries.
- Modify `orders/services.py`: replace pending-only deletion with status cancellation and financial reversal orchestration.
- Modify `orders/views.py`: call the new service and expose review filter/count context.
- Modify `orders/templates/create_order.html`: update cancellation copy.
- Modify `orders/static/orders/js/create_order.js`: update confirmation/error handling copy.
- Modify `orders/templates/orders/list_order.html`: show review badge/filter state for normal order list.
- Modify `orders/templates/admin/orders/pedidos_list.html`: show staff review count, filter, badge, and retry action.
- Modify `orders/tests.py`: add failing tests first for model/query, service, endpoint, and list behavior.
- Create migrations with `python manage.py makemigrations orders payment clients`.

## Task 1: Schema And Query Helpers

**Files:**
- Modify: `orders/models.py`
- Modify: `payment/models.py`
- Modify: `clients/models.py`
- Modify: `clients/managers.py`
- Test: `orders/tests.py`

- [ ] **Step 1: Write failing model/query tests**

Add tests that describe the desired API before fields exist:

```python
class OrderCancellationQuerySetTestCase(FastTenantTestCase):
    def setUp(self) -> None:
        self.customer = Client.objects.create(name="Cliente Query Cancelacion")
        self.active_order = Order.objects.create(
            client=self.customer,
            status=OrderStatus.COMPLETED.value,
            total_amount=Decimal("10.00"),
        )
        self.cancelled_order = Order.objects.create(
            client=self.customer,
            status=OrderStatus.CANCELLED.value,
            total_amount=Decimal("20.00"),
        )
        self.review_order = Order.objects.create(
            client=self.customer,
            status=OrderStatus.COMPLETED.value,
            total_amount=Decimal("30.00"),
            cancellation_review_required=True,
            cancellation_review_reason="Saldo insuficiente",
        )

    def test_active_excludes_cancelled_orders(self) -> None:
        self.assertQuerySetEqual(
            Order.objects.active().order_by("id"),
            [self.active_order, self.review_order],
            transform=lambda order: order,
        )

    def test_cancelled_returns_only_cancelled_orders(self) -> None:
        self.assertQuerySetEqual(
            Order.objects.cancelled(),
            [self.cancelled_order],
            transform=lambda order: order,
        )

    def test_review_required_returns_orders_waiting_for_staff_review(self) -> None:
        self.assertQuerySetEqual(
            Order.objects.review_required(),
            [self.review_order],
            transform=lambda order: order,
        )
```

- [ ] **Step 2: Run test to verify RED**

Run:

```bash
.venv/bin/python manage.py test orders.tests.OrderCancellationQuerySetTestCase --verbosity=1
```

Expected: FAIL because `cancellation_review_required` and queryset methods do not exist.

- [ ] **Step 3: Implement schema/model changes**

Add fields to `Order`:

```python
cancellation_review_required = models.BooleanField(default=False, db_index=True)
cancellation_review_reason = models.TextField(blank=True, null=True)
cancellation_requested_at = models.DateTimeField(null=True, blank=True)
cancellation_requested_by = models.ForeignKey(
    settings.AUTH_USER_MODEL,
    null=True,
    blank=True,
    on_delete=models.SET_NULL,
    related_name="cancellation_requested_orders",
)
```

Add `OrderQuerySet.active()`, `cancelled()`, `including_cancelled()`, and `review_required()` plus manager pass-through methods.

Add payment choice:

```python
("reversed", "Revertido")
```

Add balance transaction choices:

```python
("payment_reversal", "Reversión de pago con saldo")
("added_in_order_reversal", "Reversión de saldo agregado en venta")
```

Add credit transaction choices:

```python
("purchase_reversal", "Reversión de compra a crédito")
("payment_reversal", "Reversión de pago de deuda")
```

Update validation and managers so balance `payment_reversal` is money-in, balance `added_in_order_reversal` is money-out, credit `payment_reversal` increases debt, and credit `purchase_reversal` decreases debt.

- [ ] **Step 4: Create migrations**

Run:

```bash
.venv/bin/python manage.py makemigrations orders payment clients
```

Expected: one migration per changed app, with the fields and choice changes above.

- [ ] **Step 5: Run test to verify GREEN**

Run:

```bash
.venv/bin/python manage.py test orders.tests.OrderCancellationQuerySetTestCase --verbosity=1
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add orders/models.py payment/models.py clients/models.py clients/managers.py orders/tests.py orders/migrations payment/migrations clients/migrations
git commit -m "feat: add cancellation review schema"
```

## Task 2: Financial Reversal Helpers

**Files:**
- Modify: `clients/services/balance_service.py`
- Test: `orders/tests.py`

- [ ] **Step 1: Write failing helper tests**

Add service-level tests:

```python
class OrderCancellationFinancialReversalTestCase(FastTenantTestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(username="cancel_finance_user")
        self.customer = Client.objects.create(name="Cliente Reversas", balance=Decimal("100.00"), credit_limit=Decimal("500.00"))
        self.order = Order.objects.create(client=self.customer, status=OrderStatus.COMPLETED.value, total_amount=Decimal("50.00"))

    def test_reverse_balance_payment_restores_client_balance(self) -> None:
        payment = Payment(
            amount=Decimal("40.00"),
            method="balance",
            client=self.customer,
            order=self.order,
            status="completed",
            balance_used=Decimal("40.00"),
            created_by=self.user,
        )
        payment.save(apply_accounting=False)
        self.customer.balance = Decimal("60.00")
        self.customer.save(update_fields=["balance"])

        tx = balance_service.reverse_balance_payment(payment=payment, user=self.user)

        self.customer.refresh_from_db()
        self.assertEqual(self.customer.balance, Decimal("100.00"))
        self.assertEqual(tx.transaction_type, "payment_reversal")
        self.assertEqual(tx.reference_payment, payment)

    def test_reverse_credit_purchase_reduces_client_debt(self) -> None:
        self.customer.current_debt = Decimal("75.00")
        self.customer.save(update_fields=["current_debt"])

        tx = balance_service.reverse_credit_purchase(
            client=self.customer,
            amount=Decimal("75.00"),
            user=self.user,
            reference_order=self.order,
            reference_payment=None,
            notes="Reversa de prueba",
        )

        self.customer.refresh_from_db()
        self.assertEqual(self.customer.current_debt, Decimal("0.00"))
        self.assertEqual(tx.transaction_type, "purchase_reversal")
```

- [ ] **Step 2: Run test to verify RED**

Run:

```bash
.venv/bin/python manage.py test orders.tests.OrderCancellationFinancialReversalTestCase --verbosity=1
```

Expected: FAIL because helper functions do not exist.

- [ ] **Step 3: Implement helpers**

Add typed helpers in `clients/services/balance_service.py`:

```python
def reverse_balance_payment(payment: "Payment", user: "User | None" = None) -> "BalanceTransaction":
    amount = payment.balance_used or payment.amount
    return add_balance(
        client=payment.client,
        amount=amount,
        transaction_type="payment_reversal",
        user=user,
        reference_order=payment.order,
        reference_payment=payment,
        notes=f"Reversión de pago con saldo - Pedido #{payment.order_id}",
    )

def reverse_added_order_balance(
    client: "Client",
    amount: Decimal,
    user: "User | None",
    reference_order: "Order",
) -> "BalanceTransaction | None":
    return deduct_balance(
        client=client,
        amount=amount,
        transaction_type="added_in_order_reversal",
        user=user,
        reference_order=reference_order,
        notes=f"Reversión de saldo agregado en venta - Pedido #{reference_order.id}",
    )

def reverse_credit_purchase(
    client: "Client",
    amount: Decimal,
    user: "User | None" = None,
    reference_order: "Order | None" = None,
    reference_payment: "Payment | None" = None,
    notes: str | None = None,
) -> "CreditTransaction":
    paid_amount = pay_debt(
        client=client,
        amount=amount,
        transaction_type="purchase_reversal",
        user=user,
        reference_order=reference_order,
        reference_payment=reference_payment,
        notes=notes or f"Reversión de compra a crédito - Pedido #{reference_order.id if reference_order else ''}",
    )
    if paid_amount != amount:
        raise ValueError("No se pudo revertir completo el crédito del pedido.")
    transaction = client.credit_transactions.filter(
        transaction_type="purchase_reversal",
        amount=amount,
        reference_order=reference_order,
        reference_payment=reference_payment,
    ).order_by("-created_at").first()
    if transaction is None:
        raise ValueError("No se encontró la transacción de reversión de crédito.")
    return transaction

def reverse_credit_payment(
    client: "Client",
    amount: Decimal,
    user: "User | None" = None,
    reference_order: "Order | None" = None,
    reference_payment: "Payment | None" = None,
    notes: str | None = None,
) -> "CreditTransaction":
    return add_debt(
        client=client,
        amount=amount,
        transaction_type="payment_reversal",
        user=user,
        reference_order=reference_order,
        reference_payment=reference_payment,
        notes=notes or f"Reversión de pago de deuda - Pedido #{reference_order.id if reference_order else ''}",
    )
```

- [ ] **Step 4: Run helper tests to verify GREEN**

Run:

```bash
.venv/bin/python manage.py test orders.tests.OrderCancellationFinancialReversalTestCase --verbosity=1
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add clients/services/balance_service.py orders/tests.py
git commit -m "feat: add financial reversal helpers"
```

## Task 3: Order Cancellation Service

**Files:**
- Modify: `orders/services.py`
- Test: `orders/tests.py`

- [ ] **Step 1: Write failing service tests**

Update existing cancellation tests and add new tests for:

```python
def test_cancel_pending_order_marks_cancelled_without_deleting(self) -> None:
    result = services.cancel_order(order=self.order, user=self.user)
    self.assertTrue(result["success"])
    self.order.refresh_from_db()
    self.assertEqual(self.order.status, OrderStatus.CANCELLED.value)
    self.assertTrue(OrderProduct.objects.filter(order=self.order).exists())

def test_cancel_completed_external_payment_marks_payment_reversed(self) -> None:
    self.order.status = OrderStatus.COMPLETED.value
    self.order.save(update_fields=["status"])
    payment = Payment.objects.create(amount=Decimal("50.00"), method="cash", client=self.customer, order=self.order, status="completed", created_by=self.user)
    result = services.cancel_order(order=self.order, user=self.user)
    self.assertTrue(result["success"])
    payment.refresh_from_db()
    self.assertEqual(payment.status, "reversed")

def test_cancel_order_with_spent_added_balance_marks_review_required(self) -> None:
    self.customer.balance = Decimal("0.00")
    self.customer.save(update_fields=["balance"])
    BalanceTransaction.objects.create(
        client=self.customer,
        transaction_type="added_in_order",
        amount=Decimal("50.00"),
        balance_before=Decimal("0.00"),
        balance_after=Decimal("50.00"),
        reference_order=self.order,
        created_by=self.user,
    )
    result = services.cancel_order(order=self.order, user=self.user)
    self.assertFalse(result["success"])
    self.order.refresh_from_db()
    self.assertTrue(self.order.cancellation_review_required)
```

- [ ] **Step 2: Run test to verify RED**

Run:

```bash
.venv/bin/python manage.py test orders.tests.CancelOrderServiceTestCase --verbosity=1
```

Expected: FAIL because `services.cancel_order()` does not exist and old behavior deletes pending orders.

- [ ] **Step 3: Implement `orders.services.cancel_order()`**

Implement status-based cancellation with row locks, invoice block, added-balance block, balance/credit reversals, payment `reversed` updates, order `CANCELLED`, and review metadata clearing on success. Keep `cancel_pending_order()` as a compatibility wrapper calling `cancel_order()`.

- [ ] **Step 4: Run service tests to verify GREEN**

Run:

```bash
.venv/bin/python manage.py test orders.tests.CancelOrderServiceTestCase --verbosity=1
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add orders/services.py orders/tests.py
git commit -m "feat: cancel orders by status with reversals"
```

## Task 4: Endpoint And Orders List Review UI

**Files:**
- Modify: `orders/views.py`
- Modify: `orders/templates/create_order.html`
- Modify: `orders/static/orders/js/create_order.js`
- Modify: `orders/templates/orders/list_order.html`
- Modify: `orders/templates/admin/orders/pedidos_list.html`
- Test: `orders/tests.py`

- [ ] **Step 1: Write failing endpoint/list tests**

Add tests that assert:

```python
def test_cancel_order_endpoint_allows_completed_order(self) -> None:
    self.order.status = OrderStatus.COMPLETED.value
    self.order.save(update_fields=["status"])
    response = self.client.post(reverse("orders:cancel_order", kwargs={"order_pk": self.order.pk}), data=json.dumps({}), content_type="application/json")
    self.assertEqual(response.status_code, 200)
    self.order.refresh_from_db()
    self.assertEqual(self.order.status, OrderStatus.CANCELLED.value)

def test_orders_list_shows_review_badge_for_blocked_cancellation(self) -> None:
    self.order.cancellation_review_required = True
    self.order.cancellation_review_reason = "Saldo insuficiente"
    self.order.save(update_fields=["cancellation_review_required", "cancellation_review_reason"])
    response = self.client.get(reverse("orders:list"))
    self.assertContains(response, "Requiere revisión de cancelación")
```

- [ ] **Step 2: Run test to verify RED**

Run:

```bash
.venv/bin/python manage.py test orders.tests.CancelOrderViewTestCase orders.tests.OrdersDashboardBulkActionTestCase --verbosity=1
```

Expected: FAIL because completed endpoint still returns 400 and list templates do not show review state.

- [ ] **Step 3: Implement endpoint/list UI**

Update `orders.views.cancel_order()` to call `order_services.cancel_order()`. Extend `_build_orders_list_context()` with virtual status `REVIEW_REQUIRED`, review count, and filter logic. Update templates to show review badges/count/action and JS confirmation copy.

- [ ] **Step 4: Run endpoint/list tests to verify GREEN**

Run:

```bash
.venv/bin/python manage.py test orders.tests.CancelOrderViewTestCase orders.tests.OrdersDashboardBulkActionTestCase --verbosity=1
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add orders/views.py orders/templates/create_order.html orders/static/orders/js/create_order.js orders/templates/orders/list_order.html orders/templates/admin/orders/pedidos_list.html orders/tests.py
git commit -m "feat: show cancellation review in orders UI"
```

## Task 5: Full Verification

**Files:**
- No new files.

- [ ] **Step 1: Run migrations check**

Run:

```bash
.venv/bin/python manage.py makemigrations --check --dry-run
```

Expected: no model changes detected.

- [ ] **Step 2: Run focused tests**

Run:

```bash
.venv/bin/python manage.py test orders payment clients --verbosity=1
```

Expected: PASS.

- [ ] **Step 3: Run full test suite if focused tests pass**

Run:

```bash
.venv/bin/python manage.py test --verbosity=1
```

Expected: PASS.

- [ ] **Step 4: Commit final fixes if verification required changes**

```bash
git add .
git commit -m "fix: stabilize order cancellation review"
```
