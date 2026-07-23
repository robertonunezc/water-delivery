# Client Unpaid Order Payments Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a client-level payment flow that lets staff select one or more unpaid orders from the client detail page, pay them together, preserve credit audit history, and add overpayment to client balance.

**Architecture:** Add a payment orchestration service in `payment/services.py` that validates selected orders and settles each order atomically. Add a client-scoped view and template in the `clients` app for reviewing and submitting selected orders. Update `clients/templates/client_detail.html` so overdue and recent-sales rows expose unpaid-order selection and route payment actions to the new page.

**Tech Stack:** Django 5.2, Django templates, Django test client, existing `Payment`, `Order`, `CreditTransaction`, and `BalanceTransaction` models.

## Global Constraints

- The selector includes any unpaid order for the viewed client, not only credit orders.
- Underpayment is blocked.
- Overpayment is added to the client's balance.
- Do not change `Order.type` after payment.
- Do not allow `pending_credit` as a settlement method.
- Financial writes must be wrapped in `transaction.atomic()`.
- Use existing model/service patterns; domain orchestration belongs in services.
- Type hints are required for all new function signatures.

---

## File Structure

- Modify `payment/services.py`: add validation helpers and a `pay_client_orders()` orchestration service. Reuse `settle_credit_order_payment()` for credit orders with pending credit markers and `process_single_payment()` for normal unpaid orders.
- Modify `clients/views.py`: add GET/POST view helpers for selected unpaid order payment review and submit.
- Modify `clients/urls.py`: add a client-scoped payment URL.
- Create `clients/templates/pay_selected_orders.html`: review page with selected orders, prepopulated amount, and payment method selector.
- Modify `clients/templates/client_detail.html`: add selectable unpaid rows, `Pagar seleccionados`, and recent-sales action menu.
- Modify `clients/tests.py`: add client detail UI tests and client-level payment flow tests.

---

### Task 1: Payment Service For Multi-Order Settlement

**Files:**
- Modify: `payment/services.py`
- Test: `clients/tests.py`

**Interfaces:**
- Consumes: `process_single_payment(order: Order, payment_method: str, amount: Decimal, request_user: User, credit_note: Optional[str] = None)`, `settle_credit_order_payment(order: Order, payment_method: str, amount: Decimal, request_user: User)`, `balance_service.add_balance(...)`
- Produces:
  - `class ClientOrderPaymentError(ValueError)`
  - `get_unpaid_amount(order: Order) -> Decimal`
  - `get_selected_unpaid_orders(client: Client, order_ids: list[int]) -> list[Order]`
  - `pay_client_orders(client: Client, orders: list[Order], payment_method: str, amount: Decimal, request_user: User) -> dict[str, object]`

- [ ] **Step 1: Write failing service tests**

Add tests to `clients/tests.py`:

```python
class ClientSelectedOrderPaymentServiceTests(FastTenantTestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(username='selected-pay-user', password='testpass123')
        self.customer = Client.objects.create(name='Cliente pagos seleccionados', active=True, credit_limit=Decimal('1000.00'), can_pay_with_credit=True)
        self.other_customer = Client.objects.create(name='Cliente ajeno', active=True)

    def _order(self, client: Client, total: Decimal, status: str = OrderStatus.COMPLETED.value) -> Order:
        return Order.objects.create(client=client, status=status, total_amount=total)

    def test_pay_client_orders_pays_multiple_unpaid_orders(self) -> None:
        from payment import services as payment_services

        first = self._order(self.customer, Decimal('100.00'))
        second = self._order(self.customer, Decimal('80.00'))

        result = payment_services.pay_client_orders(
            client=self.customer,
            orders=[first, second],
            payment_method='cash',
            amount=Decimal('180.00'),
            request_user=self.user,
        )

        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(result['selected_total'], Decimal('180.00'))
        self.assertEqual(result['balance_added'], Decimal('0.00'))
        self.assertTrue(first.is_paid)
        self.assertTrue(second.is_paid)
        self.assertEqual(Payment.objects.filter(order__in=[first, second], method='cash', status='completed').count(), 2)

    def test_pay_client_orders_blocks_underpayment(self) -> None:
        from payment import services as payment_services

        first = self._order(self.customer, Decimal('100.00'))
        second = self._order(self.customer, Decimal('80.00'))

        with self.assertRaisesRegex(payment_services.ClientOrderPaymentError, 'menor al total seleccionado'):
            payment_services.pay_client_orders(
                client=self.customer,
                orders=[first, second],
                payment_method='cash',
                amount=Decimal('179.99'),
                request_user=self.user,
            )

        self.assertFalse(Payment.objects.filter(order__in=[first, second], method='cash').exists())

    def test_pay_client_orders_rejects_order_from_another_client(self) -> None:
        from payment import services as payment_services

        own_order = self._order(self.customer, Decimal('100.00'))
        other_order = self._order(self.other_customer, Decimal('80.00'))

        with self.assertRaisesRegex(payment_services.ClientOrderPaymentError, 'no pertenece al cliente'):
            payment_services.pay_client_orders(
                client=self.customer,
                orders=[own_order, other_order],
                payment_method='cash',
                amount=Decimal('180.00'),
                request_user=self.user,
            )

    def test_pay_client_orders_settles_credit_and_preserves_history(self) -> None:
        from payment import services as payment_services

        self.customer.current_debt = Decimal('100.00')
        self.customer.save(update_fields=['current_debt', 'updated_at'])
        order = self._order(self.customer, Decimal('100.00'))
        order.type = 'credito'
        order.save(update_fields=['type', 'updated_at'])
        pending_credit = Payment.objects.create(
            client=self.customer,
            order=order,
            amount=Decimal('100.00'),
            method='pending_credit',
            status='pending',
            created_by=self.user,
        )
        CreditTransaction.objects.create(
            client=self.customer,
            transaction_type='purchase',
            amount=Decimal('100.00'),
            debt_before=Decimal('0.00'),
            debt_after=Decimal('100.00'),
            credit_limit_before=Decimal('1000.00'),
            credit_limit_after=Decimal('1000.00'),
            reference_order=order,
            reference_payment=pending_credit,
            created_by=self.user,
        )

        payment_services.pay_client_orders(
            client=self.customer,
            orders=[order],
            payment_method='cash',
            amount=Decimal('100.00'),
            request_user=self.user,
        )

        order.refresh_from_db()
        pending_credit.refresh_from_db()
        self.customer.refresh_from_db()
        self.assertEqual(order.type, 'credito')
        self.assertTrue(order.is_paid)
        self.assertEqual(pending_credit.status, 'completed')
        self.assertEqual(self.customer.current_debt, Decimal('0.00'))
        self.assertTrue(CreditTransaction.objects.filter(reference_order=order, transaction_type='payment').exists())

    def test_pay_client_orders_adds_overpayment_to_balance(self) -> None:
        from payment import services as payment_services

        first = self._order(self.customer, Decimal('100.00'))
        second = self._order(self.customer, Decimal('80.00'))

        result = payment_services.pay_client_orders(
            client=self.customer,
            orders=[first, second],
            payment_method='cash',
            amount=Decimal('200.00'),
            request_user=self.user,
        )

        self.customer.refresh_from_db()
        self.assertEqual(result['balance_added'], Decimal('20.00'))
        self.assertEqual(self.customer.balance, Decimal('20.00'))
        self.assertTrue(BalanceTransaction.objects.filter(client=self.customer, amount=Decimal('20.00'), reference_order=second).exists())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test clients.tests.ClientSelectedOrderPaymentServiceTests -q`

Expected: FAIL because `payment_services.ClientOrderPaymentError` and `pay_client_orders()` do not exist.

- [ ] **Step 3: Implement service**

Add to `payment/services.py`:

```python
class ClientOrderPaymentError(ValueError):
    """Raised when a client-level order payment cannot be processed."""


def get_unpaid_amount(order: Order) -> Decimal:
    """Return the remaining unpaid amount for an order."""
    return max(
        Decimal(str(order.total_amount)) - Decimal(str(order.total_paid)),
        Decimal('0.00'),
    )


def get_selected_unpaid_orders(client, order_ids: list[int]) -> list[Order]:
    """Return selected unpaid orders for a client, preserving submitted order."""
    if not order_ids:
        raise ClientOrderPaymentError('Selecciona al menos un pedido para pagar.')

    deduped_ids = list(dict.fromkeys(order_ids))
    orders_by_id = {
        order.id: order
        for order in Order.objects.filter(pk__in=deduped_ids)
        .select_related('client')
        .prefetch_related('payments')
    }
    selected_orders = []
    for order_id in deduped_ids:
        order = orders_by_id.get(order_id)
        if order is None:
            raise ClientOrderPaymentError(f'Pedido #{order_id} no encontrado.')
        selected_orders.append(order)

    _validate_selected_orders(client=client, orders=selected_orders)
    return selected_orders


def _validate_selected_orders(client, orders: list[Order]) -> None:
    if not orders:
        raise ClientOrderPaymentError('Selecciona al menos un pedido para pagar.')

    for order in orders:
        if order.client_id != client.id:
            raise ClientOrderPaymentError(f'El pedido #{order.id} no pertenece al cliente.')
        if order.status == OrderStatus.CANCELLED.value:
            raise ClientOrderPaymentError(f'El pedido #{order.id} está cancelado.')
        if get_unpaid_amount(order) <= 0:
            raise ClientOrderPaymentError(f'El pedido #{order.id} ya está pagado.')


@transaction.atomic
def pay_client_orders(
    client,
    orders: list[Order],
    payment_method: str,
    amount: Decimal,
    request_user: User,
) -> dict[str, object]:
    """Pay selected unpaid client orders and add overpayment to balance."""
    selected_orders = get_selected_unpaid_orders(
        client=client,
        order_ids=[order.id for order in orders],
    )
    amount = Decimal(str(amount))
    selected_total = sum(
        (get_unpaid_amount(order) for order in selected_orders),
        Decimal('0.00'),
    )
    if amount < selected_total:
        raise ClientOrderPaymentError(
            f'El monto ${amount:.2f} es menor al total seleccionado ${selected_total:.2f}.'
        )

    created_payments = []
    for order in selected_orders:
        order_amount = get_unpaid_amount(order)
        if order_amount <= 0:
            raise ClientOrderPaymentError(f'El pedido #{order.id} ya está pagado.')

        pending_credit = order.payments.select_for_update().filter(
            method='pending_credit',
            status='pending',
        ).first()
        if pending_credit:
            payment, error = settle_credit_order_payment(
                order=order,
                payment_method=payment_method,
                amount=order_amount,
                request_user=request_user,
            )
        else:
            payment, error = process_single_payment(
                order=order,
                payment_method=payment_method,
                amount=order_amount,
                request_user=request_user,
            )
        if error:
            raise ClientOrderPaymentError(error['error'])
        created_payments.append(payment)

    balance_added = amount - selected_total
    if balance_added > 0:
        balance_service.add_balance(
            client=client,
            amount=balance_added,
            transaction_type='added_in_order',
            user=request_user,
            reference_order=selected_orders[-1],
            notes=(
                f'Saldo agregado por excedente en pago de pedidos '
                f'{", ".join(f"#{order.id}" for order in selected_orders)}. '
                f'Excedente: ${balance_added:.2f}.'
            ),
        )

    return {
        'selected_total': selected_total,
        'amount_received': amount,
        'balance_added': balance_added,
        'payments': created_payments,
        'orders': selected_orders,
    }
```

- [ ] **Step 4: Run tests to verify service passes**

Run: `python manage.py test clients.tests.ClientSelectedOrderPaymentServiceTests -q`

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add payment/services.py clients/tests.py
git commit -m "Add selected client order payment service"
```

---

### Task 2: Client Payment Review Page

**Files:**
- Modify: `clients/views.py`
- Modify: `clients/urls.py`
- Create: `clients/templates/pay_selected_orders.html`
- Test: `clients/tests.py`

**Interfaces:**
- Consumes: `payment.services.get_selected_unpaid_orders(client, order_ids)`, `payment.services.get_unpaid_amount(order)`, `payment.services.pay_client_orders(...)`
- Produces: URL name `clients:pay_selected_orders`

- [ ] **Step 1: Write failing view tests**

Add tests to `clients/tests.py`:

```python
class ClientSelectedOrderPaymentViewTests(FastTenantTestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(username='selected-pay-view-user', password='testpass123')
        self.customer = Client.objects.create(name='Cliente vista pagos', active=True)
        self.client.force_login(self.user)

    def _order(self, total: Decimal) -> Order:
        return Order.objects.create(client=self.customer, status=OrderStatus.COMPLETED.value, total_amount=total)

    def test_payment_page_prefills_selected_total(self) -> None:
        first = self._order(Decimal('100.00'))
        second = self._order(Decimal('80.00'))

        response = self.client.get(
            reverse('clients:pay_selected_orders', args=[self.customer.pk]),
            {'orders': [str(first.pk), str(second.pk)]},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['selected_total'], Decimal('180.00'))
        self.assertContains(response, 'value="180.00"')
        self.assertContains(response, f'#{first.pk}')
        self.assertContains(response, f'#{second.pk}')

    def test_payment_page_requires_selected_orders(self) -> None:
        response = self.client.get(reverse('clients:pay_selected_orders', args=[self.customer.pk]))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('clients:detail', args=[self.customer.pk]))

    def test_payment_page_posts_payment_and_redirects_to_client_detail(self) -> None:
        first = self._order(Decimal('100.00'))
        second = self._order(Decimal('80.00'))

        response = self.client.post(
            reverse('clients:pay_selected_orders', args=[self.customer.pk]),
            {
                'orders': [str(first.pk), str(second.pk)],
                'amount': '180.00',
                'payment_method': 'cash',
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('clients:detail', args=[self.customer.pk]))
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertTrue(first.is_paid)
        self.assertTrue(second.is_paid)

    def test_payment_page_rejects_underpayment(self) -> None:
        first = self._order(Decimal('100.00'))

        response = self.client.post(
            reverse('clients:pay_selected_orders', args=[self.customer.pk]),
            {
                'orders': [str(first.pk)],
                'amount': '99.99',
                'payment_method': 'cash',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'menor al total seleccionado')
        self.assertFalse(Payment.objects.filter(order=first, method='cash').exists())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test clients.tests.ClientSelectedOrderPaymentViewTests -q`

Expected: FAIL because URL/view/template do not exist.

- [ ] **Step 3: Add URL and view**

In `clients/urls.py`, add before `<int:pk>/` detail route:

```python
path('<int:pk>/orders/pay/', views.pay_selected_orders, name='pay_selected_orders'),
```

In `clients/views.py`, add:

```python
from payment.models import PAYMENT_METHOD_CHOICES
from payment import services as payment_services
```

Then add helpers and view:

```python
def _parse_order_ids(request: HttpRequest) -> list[int]:
    raw_order_ids = request.POST.getlist('orders') if request.method == 'POST' else request.GET.getlist('orders')
    order_ids = []
    for raw_order_id in raw_order_ids:
        try:
            order_ids.append(int(raw_order_id))
        except (TypeError, ValueError):
            continue
    return order_ids


def _selected_order_payment_context(
    client: Client,
    selected_orders: list[Order],
    *,
    amount: Decimal | None = None,
    error_message: str | None = None,
) -> dict[str, Any]:
    selected_total = sum(
        (payment_services.get_unpaid_amount(order) for order in selected_orders),
        Decimal('0.00'),
    )
    payment_types = [
        (value, label)
        for value, label in PAYMENT_METHOD_CHOICES
        if value not in {'pending_credit'}
    ]
    return {
        'client': client,
        'selected_orders': selected_orders,
        'selected_total': selected_total,
        'payment_amount': amount if amount is not None else selected_total,
        'payment_types': payment_types,
        'error_message': error_message,
    }


@login_required
def pay_selected_orders(request: HttpRequest, pk: int) -> HttpResponse:
    client = get_object_or_404(Client, pk=pk)
    order_ids = _parse_order_ids(request)

    try:
        selected_orders = payment_services.get_selected_unpaid_orders(client, order_ids)
    except payment_services.ClientOrderPaymentError as exc:
        messages.error(request, str(exc))
        return redirect('clients:detail', pk=client.pk)

    if request.method == 'POST':
        raw_amount = request.POST.get('amount', '0')
        payment_method = request.POST.get('payment_method', 'cash')
        try:
            result = payment_services.pay_client_orders(
                client=client,
                orders=selected_orders,
                payment_method=payment_method,
                amount=Decimal(str(raw_amount)),
                request_user=request.user,
            )
        except (payment_services.ClientOrderPaymentError, ValueError) as exc:
            context = _selected_order_payment_context(
                client,
                selected_orders,
                amount=Decimal(str(raw_amount or '0')),
                error_message=str(exc),
            )
            return render(request, 'pay_selected_orders.html', context)

        messages.success(
            request,
            f'Se registró el pago de {len(result["orders"])} pedido(s) por ${result["selected_total"]:.2f}.',
        )
        if result['balance_added'] > 0:
            messages.info(request, f'Se agregó ${result["balance_added"]:.2f} al saldo del cliente.')
        return redirect('clients:detail', pk=client.pk)

    context = _selected_order_payment_context(client, selected_orders)
    return render(request, 'pay_selected_orders.html', context)
```

- [ ] **Step 4: Add template**

Create `clients/templates/pay_selected_orders.html`:

```django
{% extends "base.html" %}

{% block content %}
<div class="container py-4">
  <div class="d-flex justify-content-between align-items-start mb-3">
    <div>
      <h1 class="h4 mb-1">Pagar pedidos seleccionados</h1>
      <p class="text-muted mb-0">{{ client.name }}</p>
    </div>
    <a href="{% url 'clients:detail' client.pk %}" class="btn btn-outline-secondary">Volver</a>
  </div>

  {% if error_message %}
    <div class="alert alert-danger">{{ error_message }}</div>
  {% endif %}

  <div class="row g-3">
    <div class="col-lg-8">
      <div class="card">
        <div class="card-header bg-white">
          <strong>Pedidos a pagar</strong>
        </div>
        <div class="table-responsive">
          <table class="table table-sm align-middle mb-0">
            <thead class="table-light">
              <tr>
                <th>Pedido</th>
                <th>Fecha</th>
                <th>Total</th>
                <th>Pagado</th>
                <th>Pendiente</th>
              </tr>
            </thead>
            <tbody>
              {% for order in selected_orders %}
                <tr>
                  <td><a href="{% url 'orders:get_order' order.pk %}">#{{ order.pk }}</a></td>
                  <td>{{ order.order_date|date:"d/m/Y H:i" }}</td>
                  <td>${{ order.total_amount|floatformat:2 }}</td>
                  <td>${{ order.total_paid|floatformat:2 }}</td>
                  <td class="fw-semibold text-danger">${{ order.remaining_payment_amount|floatformat:2 }}</td>
                </tr>
              {% endfor %}
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <div class="col-lg-4">
      <form method="post" class="card">
        {% csrf_token %}
        {% for order in selected_orders %}
          <input type="hidden" name="orders" value="{{ order.pk }}">
        {% endfor %}
        <div class="card-body">
          <div class="mb-3">
            <div class="text-muted small">Total seleccionado</div>
            <div class="fs-4 fw-bold">${{ selected_total|floatformat:2 }}</div>
          </div>
          <div class="mb-3">
            <label for="amount" class="form-label">Monto recibido</label>
            <input id="amount" name="amount" type="number" step="0.01" min="{{ selected_total|floatformat:2 }}" value="{{ payment_amount|floatformat:2 }}" class="form-control" required>
            <div class="form-text">Debe cubrir el total seleccionado. El excedente se agrega al saldo.</div>
          </div>
          <div class="mb-3">
            <label for="payment_method" class="form-label">Método de pago</label>
            <select id="payment_method" name="payment_method" class="form-select" required>
              {% for value, label in payment_types %}
                <option value="{{ value }}">{{ label }}</option>
              {% endfor %}
            </select>
          </div>
          <button type="submit" class="btn btn-primary w-100">Confirmar pago</button>
        </div>
      </form>
    </div>
  </div>
</div>
{% endblock %}
```

- [ ] **Step 5: Run tests to verify view passes**

Run: `python manage.py test clients.tests.ClientSelectedOrderPaymentViewTests -q`

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add clients/views.py clients/urls.py clients/templates/pay_selected_orders.html clients/tests.py
git commit -m "Add selected order payment page"
```

---

### Task 3: Client Detail Selection UI

**Files:**
- Modify: `clients/templates/client_detail.html`
- Test: `clients/tests.py`

**Interfaces:**
- Consumes: URL name `clients:pay_selected_orders`
- Produces: unpaid-order checkboxes with `name="orders"` and direct pay links to `clients:pay_selected_orders`

- [ ] **Step 1: Write failing template tests**

Add tests to `clients/tests.py`:

```python
class ClientDetailSelectedPaymentUiTests(FastTenantTestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(username='client-detail-pay-ui', password='testpass123')
        self.customer = Client.objects.create(name='Cliente UI pagos', active=True, credit_limit=Decimal('1000.00'), can_pay_with_credit=True)
        self.client.force_login(self.user)

    def test_recent_sales_unpaid_order_has_checkbox_and_pay_action(self) -> None:
        order = Order.objects.create(client=self.customer, status=OrderStatus.COMPLETED.value, total_amount=Decimal('100.00'))

        response = self.client.get(reverse('clients:detail', args=[self.customer.pk]))

        self.assertContains(response, f'name="orders" value="{order.pk}"')
        self.assertContains(response, 'Pagar seleccionados')
        self.assertContains(response, f'href="{reverse("clients:pay_selected_orders", args=[self.customer.pk])}?orders={order.pk}"')
        self.assertContains(response, 'Editar')

    def test_recent_sales_paid_order_has_no_payment_checkbox_or_pay_action(self) -> None:
        order = Order.objects.create(client=self.customer, status=OrderStatus.COMPLETED.value, total_amount=Decimal('100.00'))
        Payment.objects.create(client=self.customer, order=order, amount=Decimal('100.00'), method='cash', status='completed', created_by=self.user)

        response = self.client.get(reverse('clients:detail', args=[self.customer.pk]))

        self.assertNotContains(response, f'name="orders" value="{order.pk}"')
        self.assertNotContains(response, f'?orders={order.pk}"')

    def test_overdue_order_pay_action_points_to_selected_payment_page(self) -> None:
        config = ClientCreditConfig.objects.create(client=self.customer, payment_term_type='monthly_cutoff', cutoff_day='1')
        self.customer.current_debt = Decimal('100.00')
        self.customer.save(update_fields=['current_debt', 'updated_at'])
        order = Order.objects.create(client=self.customer, status=OrderStatus.COMPLETED.value, total_amount=Decimal('100.00'), type='credito')
        Order.objects.filter(pk=order.pk).update(order_date=timezone.now() - timedelta(days=60))
        Payment.objects.create(client=self.customer, order=order, amount=Decimal('100.00'), method='pending_credit', status='pending', created_by=self.user)
        CreditTransaction.objects.create(
            client=self.customer,
            transaction_type='purchase',
            amount=Decimal('100.00'),
            debt_before=Decimal('0.00'),
            debt_after=Decimal('100.00'),
            credit_limit_before=Decimal('1000.00'),
            credit_limit_after=Decimal('1000.00'),
            reference_order=order,
            created_by=self.user,
        )

        response = self.client.get(reverse('clients:detail', args=[self.customer.pk]))

        self.assertContains(response, '¡Atención! Pagos Vencidos')
        self.assertContains(response, f'name="orders" value="{order.pk}"')
        self.assertContains(response, f'href="{reverse("clients:pay_selected_orders", args=[self.customer.pk])}?orders={order.pk}"')
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test clients.tests.ClientDetailSelectedPaymentUiTests -q`

Expected: FAIL because the template does not render the new controls.

- [ ] **Step 3: Update overdue table UI**

In `clients/templates/client_detail.html`, in the overdue table:

```django
<form id="selected-orders-payment-form" method="get" action="{% url 'clients:pay_selected_orders' client.pk %}">
```

Add a submit button near the overdue header:

```django
<button type="submit" class="btn btn-danger btn-sm">Pagar seleccionados</button>
```

Add a checkbox column and row checkbox:

```django
<th style="width: 40px;"></th>
...
<td>
  {% if not overdue_order.is_paid and overdue_order.status != 'CANCELLED' %}
    <input class="form-check-input client-order-payment-checkbox" type="checkbox" name="orders" value="{{ overdue_order.pk }}" form="selected-orders-payment-form">
  {% endif %}
</td>
```

Change row `Pagar` to:

```django
<a href="{% url 'clients:pay_selected_orders' client.pk %}?orders={{ overdue_order.id }}" class="btn btn-sm btn-danger">Pagar</a>
```

- [ ] **Step 4: Update recent sales table UI**

In the recent-sales table, add the same checkbox column and a `Pagar seleccionados` button in the table header area:

```django
<button type="submit" class="btn btn-primary btn-sm" form="selected-orders-payment-form">Pagar seleccionados</button>
```

Change the action column to a dropdown:

```django
<div class="dropdown">
  <button class="btn btn-sm btn-outline-secondary dropdown-toggle" type="button" data-bs-toggle="dropdown" aria-expanded="false">Acciones</button>
  <ul class="dropdown-menu dropdown-menu-end">
    <li><a class="dropdown-item" href="{% url 'orders:get_order' order.id %}">Editar</a></li>
    {% if not order.is_paid and order.status != 'CANCELLED' %}
      <li><a class="dropdown-item" href="{% url 'clients:pay_selected_orders' client.pk %}?orders={{ order.id }}">Pagar</a></li>
    {% endif %}
  </ul>
</div>
```

- [ ] **Step 5: Run tests to verify UI passes**

Run: `python manage.py test clients.tests.ClientDetailSelectedPaymentUiTests -q`

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add clients/templates/client_detail.html clients/tests.py
git commit -m "Add client detail selected order payment controls"
```

---

### Task 4: Final Integration Verification

**Files:**
- Modify only if test failures reveal integration issues in touched files.

**Interfaces:**
- Consumes all previous tasks.
- Produces a verified feature ready for manual QA.

- [ ] **Step 1: Run focused tests**

Run:

```bash
python manage.py test clients.tests.ClientSelectedOrderPaymentServiceTests clients.tests.ClientSelectedOrderPaymentViewTests clients.tests.ClientDetailSelectedPaymentUiTests -q
```

Expected: PASS.

- [ ] **Step 2: Run related app tests**

Run:

```bash
python manage.py test clients payment orders -q
```

Expected: PASS.

- [ ] **Step 3: Inspect changed files**

Run:

```bash
git diff --check
git status --short
```

Expected: `git diff --check` returns no output. `git status --short` shows only intended files if anything remains uncommitted.

- [ ] **Step 4: Commit any final fixes**

If any final integration fixes were needed, run:

```bash
git add clients/views.py clients/urls.py clients/templates/client_detail.html clients/templates/pay_selected_orders.html payment/services.py clients/tests.py
git commit -m "Fix selected order payment integration"
```
