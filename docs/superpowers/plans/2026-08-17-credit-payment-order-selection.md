# Credit Payment Order Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `Gestionar credito` settle selected pending credit orders for `Pago de deuda` and `Pago con Saldo`, while removing `Condonación de deuda`.

**Architecture:** Add a focused credit-management order-scope service, extend payment settlement to accept scoped orders and an optional payer client for balance payments, then update the `pay_credit` view/template to drive the order-aware flow. Keep accounting writes in existing payment and balance services.

**Tech Stack:** Django 5.2, Django templates, Django TestCase, Decimal money values.

## Global Constraints

- Use existing soft-delete managers; do not assume default managers return deleted rows.
- Domain orchestration belongs in services and views, not templates.
- Type hints are required for all new function signatures.
- Multi-order financial writes must stay atomic.
- `Pago de deuda` and `Pago con Saldo` require selected credit orders.
- `Condonación de deuda` must be removed from the credit transaction type menu.
- Underpayment must be blocked with split-order guidance.

---

## File Structure

- Modify `clients/forms.py`: remove `forgiveness` and make `amount` validation compatible with order-selected payments.
- Create `clients/services/credit_payment_service.py`: fetch and validate open credit orders for branch/corporate credit-management scope.
- Modify `clients/services/__init__.py`: export the new helper functions only if needed by callers.
- Modify `payment/services.py`: allow paying selected orders within an allowed order scope and allow balance payments to spend a payer client balance.
- Modify `clients/views.py`: branch `pay_credit` POST behavior by transaction type and pass credit order context to the template.
- Modify `clients/templates/pay_credit.html`: render selectable credit orders, totals, difference indicator, and transaction-type toggles.
- Modify `clients/tests.py`: add focused service/view tests for order listing and settlement behavior.
- Modify `clients/tests/tests_credit_management.py`: add the form-choice regression test.

---

### Task 1: Credit Management Order Scope

**Files:**
- Create: `clients/services/credit_payment_service.py`
- Test: `clients/tests.py`

**Interfaces:**
- Consumes: `Client`, `CreditTransaction`, `Order.objects.active().unpaid()`, `payment.services.get_unpaid_amount(order: Order) -> Decimal`
- Produces: `get_open_credit_orders_for_credit_management(client: Client) -> list[Order]`
- Produces: `get_selected_credit_orders_for_credit_management(client: Client, order_ids: list[int]) -> list[Order]`

- [ ] **Step 1: Write failing tests for branch and corporate order scope**

Add a new `ClientCreditManagementOrderScopeTests(FastTenantTestCase)` class to `clients/tests.py` with helpers:

```python
def _credit_order(
    self,
    client: Client,
    amount: Decimal,
    *,
    order_date,
    credit_account: Client | None = None,
    status: str = OrderStatus.COMPLETED.value,
) -> Order:
    order = Order.objects.create(
        client=client,
        status=status,
        total_amount=amount,
        type='credito',
    )
    Order.objects.filter(pk=order.pk).update(order_date=order_date)
    order.refresh_from_db()
    pending_credit = Payment.objects.create(
        client=client,
        order=order,
        amount=amount,
        method='pending_credit',
        status='pending',
        created_by=self.user,
    )
    CreditTransaction.objects.create(
        client=credit_account or client.get_credit_account(),
        transaction_type='purchase',
        amount=amount,
        debt_before=Decimal('0.00'),
        debt_after=amount,
        credit_limit_before=Decimal('1000.00'),
        credit_limit_after=Decimal('1000.00'),
        reference_order=order,
        reference_payment=pending_credit,
        created_by=self.user,
    )
    return order
```

Add tests:

```python
def test_branch_scope_lists_own_pending_credit_orders_newest_first(self) -> None:
    from clients.services.credit_payment_service import (
        get_open_credit_orders_for_credit_management,
    )

    older = self._credit_order(
        self.branch,
        Decimal('100.00'),
        order_date=timezone.now() - timedelta(days=2),
        credit_account=self.corporate,
    )
    newer = self._credit_order(
        self.branch,
        Decimal('150.00'),
        order_date=timezone.now() - timedelta(days=1),
        credit_account=self.corporate,
    )

    orders = get_open_credit_orders_for_credit_management(self.branch)

    self.assertEqual([order.pk for order in orders], [newer.pk, older.pk])
```

```python
def test_corporate_scope_lists_all_branch_credit_orders_newest_first(self) -> None:
    from clients.services.credit_payment_service import (
        get_open_credit_orders_for_credit_management,
    )

    override_branch = Client.objects.create(
        name='Sucursal credito propio',
        type='branch',
        corporate=self.corporate,
        credit_override_enabled=True,
        credit_limit=Decimal('1000.00'),
        can_pay_with_credit=True,
    )
    inherited_order = self._credit_order(
        self.branch,
        Decimal('100.00'),
        order_date=timezone.now() - timedelta(days=2),
        credit_account=self.corporate,
    )
    override_order = self._credit_order(
        override_branch,
        Decimal('180.00'),
        order_date=timezone.now() - timedelta(days=1),
        credit_account=override_branch,
    )

    orders = get_open_credit_orders_for_credit_management(self.corporate)

    self.assertEqual([order.pk for order in orders], [override_order.pk, inherited_order.pk])
```

```python
def test_scope_excludes_paid_cancelled_and_out_of_scope_orders(self) -> None:
    from clients.services.credit_payment_service import (
        get_open_credit_orders_for_credit_management,
    )

    selectable = self._credit_order(
        self.branch,
        Decimal('100.00'),
        order_date=timezone.now() - timedelta(days=1),
        credit_account=self.corporate,
    )
    paid = self._credit_order(
        self.branch,
        Decimal('80.00'),
        order_date=timezone.now(),
        credit_account=self.corporate,
    )
    Payment.objects.create(
        client=self.branch,
        order=paid,
        amount=Decimal('80.00'),
        method='cash',
        status='completed',
        created_by=self.user,
    )
    self._credit_order(
        self.other_branch,
        Decimal('90.00'),
        order_date=timezone.now(),
        credit_account=self.other_corporate,
    )
    self._credit_order(
        self.branch,
        Decimal('70.00'),
        order_date=timezone.now(),
        credit_account=self.corporate,
        status=OrderStatus.CANCELLED.value,
    )

    orders = get_open_credit_orders_for_credit_management(self.corporate)

    self.assertEqual([order.pk for order in orders], [selectable.pk])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python manage.py test clients.tests.ClientCreditManagementOrderScopeTests --verbosity 1 --noinput`

Expected: FAIL because `clients.services.credit_payment_service` does not exist.

- [ ] **Step 3: Implement the scope service**

Create `clients/services/credit_payment_service.py`:

```python
from __future__ import annotations

from decimal import Decimal
from typing import Iterable

from clients.models import Client, CreditTransaction
from orders.models import Order
from payment import services as payment_services


class CreditManagementOrderError(ValueError):
    """Raised when selected credit-management orders are invalid."""


def get_open_credit_orders_for_credit_management(client: Client) -> list[Order]:
    """Return open credit orders selectable from the client's credit screen."""
    credit_transactions = CreditTransaction.objects.filter(
        transaction_type='purchase',
        reference_order__isnull=False,
    )
    if client.type == 'corporate':
        credit_transactions = credit_transactions.filter(
            reference_order__client__corporate=client,
        )
    else:
        credit_transactions = credit_transactions.filter(
            client=client.get_credit_account(),
            reference_order__client=client,
        )

    credit_order_ids = credit_transactions.values('reference_order_id')
    orders = (
        Order.objects.active()
        .unpaid()
        .filter(
            pk__in=credit_order_ids,
            payments__method='pending_credit',
            payments__status='pending',
        )
        .select_related('client', 'client__corporate')
        .prefetch_related('payments')
        .distinct()
        .order_by('-order_date', '-id')
    )
    return list(orders)


def get_selected_credit_orders_for_credit_management(
    client: Client,
    order_ids: list[int],
) -> list[Order]:
    """Return selected open credit orders for this credit-management scope."""
    if not order_ids:
        raise CreditManagementOrderError('Selecciona al menos un pedido a crédito para pagar.')

    open_orders = get_open_credit_orders_for_credit_management(client)
    open_orders_by_id = {order.pk: order for order in open_orders}
    selected_orders = []
    for order_id in _dedupe_order_ids(order_ids):
        order = open_orders_by_id.get(order_id)
        if order is None:
            raise CreditManagementOrderError(
                f'El pedido #{order_id} no está disponible para gestionar crédito.'
            )
        selected_orders.append(order)
    return selected_orders


def get_selected_credit_orders_total(orders: Iterable[Order]) -> Decimal:
    """Return the remaining total for selected credit orders."""
    return sum(
        (payment_services.get_unpaid_amount(order) for order in orders),
        Decimal('0.00'),
    )


def _dedupe_order_ids(order_ids: list[int]) -> list[int]:
    return list(dict.fromkeys(order_ids))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python manage.py test clients.tests.ClientCreditManagementOrderScopeTests --verbosity 1 --noinput`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add clients/services/credit_payment_service.py clients/tests.py
git commit -m "feat: add credit management order scope"
```

---

### Task 2: Scoped Order Payment Support

**Files:**
- Modify: `payment/services.py`
- Test: `clients/tests.py`

**Interfaces:**
- Consumes: `payment_services.pay_client_orders(...)`
- Produces: `pay_client_orders(..., allowed_order_ids: list[int] | None = None, payment_client: Client | None = None) -> dict[str, object]`
- Produces: `process_single_payment(..., payment_client: Client | None = None) -> tuple[Payment | None, dict[str, str] | None]`
- Produces: `settle_credit_order_payment(..., payment_client: Client | None = None) -> tuple[Payment | None, dict[str, str] | None]`

- [ ] **Step 1: Write failing tests for corporate scoped settlement**

Add to `ClientCreditManagementOrderScopeTests` in `clients/tests.py`:

```python
def test_pay_client_orders_allows_corporate_scope_for_branch_credit_orders(self) -> None:
    from clients.services.credit_payment_service import (
        get_open_credit_orders_for_credit_management,
    )
    from payment import services as payment_services

    order = self._credit_order(
        self.branch,
        Decimal('100.00'),
        order_date=timezone.now(),
        credit_account=self.corporate,
    )
    self.corporate.current_debt = Decimal('100.00')
    self.corporate.save(update_fields=['current_debt', 'updated_at'])
    allowed_orders = get_open_credit_orders_for_credit_management(self.corporate)

    result = payment_services.pay_client_orders(
        client=self.corporate,
        orders=[order],
        payment_method='cash',
        amount=Decimal('100.00'),
        request_user=self.user,
        allowed_order_ids=[allowed_order.pk for allowed_order in allowed_orders],
    )

    self.assertEqual(result['selected_total'], Decimal('100.00'))
    self.corporate.refresh_from_db()
    self.assertEqual(self.corporate.current_debt, Decimal('0.00'))
    self.assertTrue(order.payments.filter(method='cash', client=self.branch).exists())
```

```python
def test_corporate_balance_payment_spends_corporate_balance_for_branch_order(self) -> None:
    from clients.services.credit_payment_service import (
        get_open_credit_orders_for_credit_management,
    )
    from payment import services as payment_services

    self.corporate.balance = Decimal('120.00')
    self.corporate.current_debt = Decimal('100.00')
    self.corporate.save(update_fields=['balance', 'current_debt', 'updated_at'])
    order = self._credit_order(
        self.branch,
        Decimal('100.00'),
        order_date=timezone.now(),
        credit_account=self.corporate,
    )
    allowed_orders = get_open_credit_orders_for_credit_management(self.corporate)

    payment_services.pay_client_orders(
        client=self.corporate,
        orders=[order],
        payment_method='balance',
        amount=Decimal('100.00'),
        request_user=self.user,
        allowed_order_ids=[allowed_order.pk for allowed_order in allowed_orders],
        payment_client=self.corporate,
    )

    self.corporate.refresh_from_db()
    self.branch.refresh_from_db()
    self.assertEqual(self.corporate.balance, Decimal('20.00'))
    self.assertEqual(self.branch.balance, Decimal('0.00'))
    self.assertTrue(order.payments.filter(method='balance', client=self.corporate).exists())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python manage.py test clients.tests.ClientCreditManagementOrderScopeTests --verbosity 1 --noinput`

Expected: FAIL with `got an unexpected keyword argument 'allowed_order_ids'`.

- [ ] **Step 3: Extend payment service signatures and validation**

In `payment/services.py`:

```python
def get_selected_unpaid_orders(
    client: "Client",
    order_ids: list[int],
    *,
    allowed_order_ids: list[int] | None = None,
) -> list[Order]:
```

Pass `allowed_order_ids` into `_validate_selected_orders(...)`.

```python
def _validate_selected_orders(
    client: "Client",
    orders: list[Order],
    *,
    allowed_order_ids: list[int] | None = None,
) -> None:
    allowed_ids = set(allowed_order_ids or [])
    for order in orders:
        if allowed_order_ids is not None:
            if order.pk not in allowed_ids:
                raise ClientOrderPaymentError(f'El pedido #{order.id} no pertenece al alcance seleccionado.')
        elif order.client_id != client.id:
            raise ClientOrderPaymentError(f'El pedido #{order.id} no pertenece al cliente.')
```

Extend:

```python
def process_single_payment(
    order: Order,
    payment_method: str,
    amount: Decimal,
    request_user: User,
    credit_note: Optional[str] = None,
    payment_client: "Client | None" = None,
) -> tuple[Optional[Payment], Optional[dict[str, str]]]:
    client = payment_client or order.client
```

Extend:

```python
def settle_credit_order_payment(
    order: Order,
    payment_method: str,
    amount: Decimal,
    request_user: User,
    payment_client: "Client | None" = None,
) -> tuple[Optional[Payment], Optional[dict[str, str]]]:
```

Pass `payment_client=payment_client` to `process_single_payment`.

Extend:

```python
def pay_client_orders(
    client: "Client",
    orders: list[Order],
    payment_method: str,
    amount: Decimal,
    request_user: User,
    allowed_order_ids: list[int] | None = None,
    payment_client: "Client | None" = None,
) -> dict[str, object]:
```

Pass `allowed_order_ids` into `get_selected_unpaid_orders(...)`, and pass `payment_client` into `settle_credit_order_payment(...)` and `process_single_payment(...)`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python manage.py test clients.tests.ClientCreditManagementOrderScopeTests clients.tests.ClientOrderPaymentServiceTests payment.tests.CreditOrderSettlementTests --verbosity 1 --noinput`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add payment/services.py clients/tests.py
git commit -m "feat: support scoped credit order settlement"
```

---

### Task 3: Credit Form and View Behavior

**Files:**
- Modify: `clients/forms.py`
- Modify: `clients/views.py`
- Test: `clients/tests/tests_credit_management.py`
- Test: `clients/tests.py`

**Interfaces:**
- Consumes: `get_open_credit_orders_for_credit_management(client)`
- Consumes: `get_selected_credit_orders_for_credit_management(client, order_ids)`
- Consumes: `payment_services.pay_client_orders(...)`
- Produces: `pay_credit` context keys `credit_orders`, `selected_order_ids`, `selected_total`, `settlement_payment_types`, `credit_account`, `error_message`

- [ ] **Step 1: Write failing form-choice test**

Add to `CreditFormFieldTests` in `clients/tests/tests_credit_management.py`:

```python
def test_manual_credit_transaction_form_removes_forgiveness(self) -> None:
    from clients.forms import ManualCreditTransactionForm

    form = ManualCreditTransactionForm()

    self.assertNotIn('forgiveness', dict(form.fields['transaction_type'].choices))
```

- [ ] **Step 2: Write failing pay-credit view tests**

Add `ClientPayCreditOrderSelectionViewTests(FastTenantTestCase)` to `clients/tests.py`:

```python
def test_pay_credit_requires_selected_orders_for_payment(self) -> None:
    response = self.client.post(
        reverse('clients:pay_credit', args=[self.branch.pk]),
        {
            'client': self.branch.pk,
            'transaction_type': 'payment',
            'amount': '100.00',
            'description': 'Pago recibido',
            'notes': 'Pago recibido con referencia bancaria.',
            'payment_method': 'cash',
        },
    )

    self.assertEqual(response.status_code, 200)
    self.assertContains(response, 'Selecciona al menos un pedido a crédito para pagar.')
```

```python
def test_pay_credit_blocks_underpayment_with_split_guidance(self) -> None:
    order = self._credit_order(
        self.branch,
        Decimal('150.00'),
        order_date=timezone.now(),
        credit_account=self.corporate,
    )
    self.corporate.current_debt = Decimal('150.00')
    self.corporate.save(update_fields=['current_debt', 'updated_at'])

    response = self.client.post(
        reverse('clients:pay_credit', args=[self.branch.pk]),
        {
            'client': self.branch.pk,
            'transaction_type': 'payment',
            'orders': [str(order.pk)],
            'amount': '100.00',
            'description': 'Pago recibido',
            'notes': 'Pago recibido con referencia bancaria.',
            'payment_method': 'cash',
        },
    )

    self.assertEqual(response.status_code, 200)
    self.assertContains(response, 'Puede dividir un pedido antes de continuar.')
```

```python
def test_pay_credit_payment_settles_orders_and_adds_overpayment_to_balance(self) -> None:
    order = self._credit_order(
        self.branch,
        Decimal('150.00'),
        order_date=timezone.now(),
        credit_account=self.corporate,
    )
    self.corporate.current_debt = Decimal('150.00')
    self.corporate.save(update_fields=['current_debt', 'updated_at'])

    response = self.client.post(
        reverse('clients:pay_credit', args=[self.branch.pk]),
        {
            'client': self.branch.pk,
            'transaction_type': 'payment',
            'orders': [str(order.pk)],
            'amount': '200.00',
            'description': 'Pago recibido',
            'notes': 'Pago recibido con referencia bancaria.',
            'payment_method': 'cash',
        },
    )

    self.assertEqual(response.status_code, 302)
    self.corporate.refresh_from_db()
    self.branch.refresh_from_db()
    order.refresh_from_db()
    self.assertEqual(self.corporate.current_debt, Decimal('0.00'))
    self.assertEqual(self.branch.balance, Decimal('50.00'))
    self.assertTrue(order.is_paid)
```

```python
def test_pay_credit_balance_payment_uses_screen_client_balance(self) -> None:
    self.corporate.balance = Decimal('160.00')
    self.corporate.current_debt = Decimal('150.00')
    self.corporate.save(update_fields=['balance', 'current_debt', 'updated_at'])
    order = self._credit_order(
        self.branch,
        Decimal('150.00'),
        order_date=timezone.now(),
        credit_account=self.corporate,
    )

    response = self.client.post(
        reverse('clients:pay_credit', args=[self.corporate.pk]),
        {
            'client': self.corporate.pk,
            'transaction_type': 'payment_from_balance',
            'orders': [str(order.pk)],
            'description': 'Pago con saldo',
            'notes': 'Pago aplicado usando saldo corporativo.',
        },
    )

    self.assertEqual(response.status_code, 302)
    self.corporate.refresh_from_db()
    self.branch.refresh_from_db()
    self.assertEqual(self.corporate.balance, Decimal('10.00'))
    self.assertEqual(self.branch.balance, Decimal('0.00'))
    self.assertEqual(self.corporate.current_debt, Decimal('0.00'))
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/python manage.py test clients.tests.tests_credit_management.CreditFormFieldTests clients.tests.ClientPayCreditOrderSelectionViewTests --verbosity 1 --noinput`

Expected: FAIL because `forgiveness` still exists and `pay_credit` does not process selected orders.

- [ ] **Step 4: Update form validation**

In `ManualCreditTransactionForm`:

- Remove `('forgiveness', 'Condonación de deuda')`.
- Change `amount` to `required=False`.
- In `clean()`, require `amount` when transaction type is `payment`, `adjustment`, or `correction`.
- Do not reject `payment` amounts greater than `client.current_debt`; the view will compare the amount to selected order totals and overpayment becomes balance.
- Do not require `amount` for `payment_from_balance`.

- [ ] **Step 5: Update `pay_credit` view**

In `clients/views.py` import:

```python
from clients.services.credit_payment_service import (
    CreditManagementOrderError,
    get_open_credit_orders_for_credit_management,
    get_selected_credit_orders_for_credit_management,
)
```

Add a helper:

```python
def _credit_payment_context(
    client: Client,
    form: ManualCreditTransactionForm,
    *,
    selected_order_ids: list[int] | None = None,
    error_message: str | None = None,
) -> dict[str, Any]:
    credit_orders = get_open_credit_orders_for_credit_management(client)
    for order in credit_orders:
        order.remaining_payment_amount = payment_services.get_unpaid_amount(order)
    selected_ids = set(selected_order_ids or [])
    selected_total = sum(
        (
            order.remaining_payment_amount
            for order in credit_orders
            if order.pk in selected_ids
        ),
        Decimal('0.00'),
    )
    settlement_payment_types = [
        (value, label)
        for value, label in PAYMENT_METHOD_CHOICES
        if value not in {'pending_credit', 'balance'}
    ]
    return {
        'form': form,
        'client': client,
        'credit_account': client.get_credit_account(),
        'credit_orders': credit_orders,
        'selected_order_ids': selected_ids,
        'selected_total': selected_total,
        'settlement_payment_types': settlement_payment_types,
        'error_message': error_message,
    }
```

In `pay_credit`, for transaction type `payment`:

```python
selected_orders = get_selected_credit_orders_for_credit_management(client, _parse_order_ids(request))
result = payment_services.pay_client_orders(
    client=client,
    orders=selected_orders,
    payment_method=request.POST.get('payment_method', 'cash'),
    amount=amount,
    request_user=request.user,
    allowed_order_ids=[order.pk for order in get_open_credit_orders_for_credit_management(client)],
)
```

Catch `CreditManagementOrderError` and `payment_services.ClientOrderPaymentError`. When the message contains `menor al total seleccionado`, replace or append: `Puede dividir un pedido antes de continuar.`

For transaction type `payment_from_balance`:

```python
selected_orders = get_selected_credit_orders_for_credit_management(client, _parse_order_ids(request))
selected_total = sum((payment_services.get_unpaid_amount(order) for order in selected_orders), Decimal('0.00'))
result = payment_services.pay_client_orders(
    client=client,
    orders=selected_orders,
    payment_method='balance',
    amount=selected_total,
    request_user=request.user,
    allowed_order_ids=[order.pk for order in get_open_credit_orders_for_credit_management(client)],
    payment_client=client,
)
```

For manual `adjustment`, `correction`, and `limit_change`, keep the existing service calls. Remove the `forgiveness` branch.

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/python manage.py test clients.tests.tests_credit_management.CreditFormFieldTests clients.tests.ClientPayCreditOrderSelectionViewTests --verbosity 1 --noinput`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add clients/forms.py clients/views.py clients/tests.py clients/tests/tests_credit_management.py
git commit -m "feat: settle credit payments through selected orders"
```

---

### Task 4: Credit Management Template and Final Verification

**Files:**
- Modify: `clients/templates/pay_credit.html`
- Test: `clients/tests.py`

**Interfaces:**
- Consumes: `credit_orders`, `selected_order_ids`, `selected_total`, `settlement_payment_types`, `error_message`, `credit_account`
- Produces: a `pay_credit` page with selectable credit orders, selected total, and amount difference indicator

- [ ] **Step 1: Write failing UI assertions**

Extend `ClientPayCreditOrderSelectionViewTests`:

```python
def test_pay_credit_page_shows_credit_orders_and_difference_widgets(self) -> None:
    order = self._credit_order(
        self.branch,
        Decimal('125.00'),
        order_date=timezone.now(),
        credit_account=self.corporate,
    )

    response = self.client.get(reverse('clients:pay_credit', args=[self.branch.pk]))

    self.assertEqual(response.status_code, 200)
    self.assertContains(response, f'name="orders" value="{order.pk}"')
    self.assertContains(response, 'Total pedidos seleccionados')
    self.assertContains(response, 'Monto agregado - total pedidos seleccionados')
    self.assertContains(response, 'Puede dividir un pedido antes de continuar.')
```

```python
def test_pay_credit_page_does_not_show_forgiveness_option(self) -> None:
    response = self.client.get(reverse('clients:pay_credit', args=[self.branch.pk]))

    self.assertNotContains(response, 'Condonación de deuda')
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python manage.py test clients.tests.ClientPayCreditOrderSelectionViewTests --verbosity 1 --noinput`

Expected: FAIL because the template does not render order-selection controls.

- [ ] **Step 3: Update template**

In `clients/templates/pay_credit.html`:

- Render `error_message` as a danger alert above the form.
- Show client metrics using `credit_account` for debt, limit, and available credit.
- Add a payment method `<select name="payment_method">` for `Pago de deuda`.
- Add a table of `credit_orders` with checkboxes:

```django
<input
    class="credit-order-checkbox"
    type="checkbox"
    name="orders"
    value="{{ order.pk }}"
    data-remaining="{{ order.remaining_payment_amount|floatformat:2 }}"
    {% if order.pk in selected_order_ids %}checked{% endif %}
>
```

- Render order id, client/branch name, date, total, paid, and remaining amount.
- Add summary elements with ids `selected-orders-total`, `payment-difference`, and `credit-payment-guidance`.
- Update JavaScript so:
  - `limit_change` shows only the new credit limit amount row.
  - `payment` shows amount, payment method, and order table.
  - `payment_from_balance` hides amount, hides payment method, and shows order table.
  - `adjustment` and `correction` show amount and hide order table.
  - checkbox and amount changes update selected total and difference.
  - underpayment shows the split-order guidance text.

- [ ] **Step 4: Run focused tests**

Run: `.venv/bin/python manage.py test clients.tests.ClientCreditManagementOrderScopeTests clients.tests.ClientPayCreditOrderSelectionViewTests clients.tests.tests_credit_management.CreditFormFieldTests --verbosity 1 --noinput`

Expected: PASS.

- [ ] **Step 5: Run broader related tests**

Run: `.venv/bin/python manage.py test clients.tests.ClientOrderPaymentServiceTests clients.tests.ClientSelectedOrderPaymentViewTests payment.tests.CreditOrderSettlementTests payment.tests.CreditOrderRegistrationRuleTests orders.tests.ProcessOrderPaymentTestCase --verbosity 1 --noinput`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add clients/templates/pay_credit.html clients/tests.py
git commit -m "feat: add credit order selection UI"
```

---

## Self-Review

- Spec coverage: Tasks cover transaction menu changes, branch/corporate credit-order listing, selected total and difference UI, underpayment blocking, overpayment to balance, balance payments using the screen client, and order-linked settlement.
- Scan result: No incomplete markers or vague implementation-only steps remain.
- Type consistency: The plan consistently uses `Client`, `Order`, `Payment`, `Decimal`, `allowed_order_ids`, and `payment_client` across service, view, and tests.
