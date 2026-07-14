# Client Detail Invoices Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show order-linked invoices on billing client detail pages and link overdue payment rows to their related invoice when present.

**Architecture:** Keep the behavior in the client detail view and template. Query invoices through `InvoiceOrderLink.order.client` so branch pages include corporate-issued invoices that contain branch orders, while the overdue table uses each prefetched order's existing `invoice_links`.

**Tech Stack:** Django 5.2, Django TestCase via `tenant_client.test_utils.FastTenantTestCase`, existing Bootstrap/Font Awesome template styles.

## Global Constraints

- Type hints required for all function signatures.
- Domain logic belongs in models, managers, querysets, or services; this change is view-context and presentation only.
- Do not filter branch invoice lists by `Invoice.client`; `Invoice.client` is the fiscal owner.
- Do not add schema changes.
- Use existing routes: invoice management links go to `admin_edit_invoice`; order links go to `orders:get_order`.

---

## File Structure

- Modify `clients/views.py`: add a typed helper to query client invoices through linked orders and pass `client_invoices` into the detail context.
- Modify `clients/templates/client_detail.html`: add the client invoice table and add the overdue table invoice column.
- Modify `clients/tests.py`: add focused client detail tests for the invoice list and overdue invoice links.

### Task 1: Client Detail Invoice List

**Files:**
- Modify: `clients/tests.py`
- Modify: `clients/views.py`
- Modify: `clients/templates/client_detail.html`

**Interfaces:**
- Consumes: `Invoice.objects.filter(invoice_links__order__client=client).distinct()`
- Produces: `client_invoices` context value for `client_detail.html`

- [ ] **Step 1: Write failing tests for billing-client invoice list**

Add these imports to `clients/tests.py`:

```python
from invoice.models import Invoice, InvoiceOrderLink
```

Add tests to `ClientDetailOrderActionsTests`:

```python
    def test_detail_lists_order_linked_invoices_for_billing_client(self) -> None:
        self.customer.requires_billing = True
        self.customer.save(update_fields=['requires_billing', 'updated_at'])
        order = Order.objects.create(
            client=self.customer,
            status=OrderStatus.COMPLETED.value,
            total_amount=Decimal('150.00'),
        )
        invoice = Invoice.objects.create(
            client=self.customer,
            amount=Decimal('150.00'),
            identifier='SER-CLIENT',
            folio='FOL-CLIENT',
            emmited_at=timezone.localdate(),
        )
        InvoiceOrderLink.objects.create(invoice=invoice, order=order)

        response = self.client.get(reverse('clients:detail', args=[self.customer.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertIn(invoice, list(response.context['client_invoices']))
        self.assertContains(response, 'Facturas')
        self.assertContains(response, 'SER-CLIENT')
        self.assertContains(response, 'FOL-CLIENT')
        self.assertContains(
            response,
            f'href="{reverse("admin_edit_invoice", args=[invoice.pk])}"',
        )

    def test_detail_hides_invoice_section_when_client_does_not_require_billing(self) -> None:
        order = Order.objects.create(
            client=self.customer,
            status=OrderStatus.COMPLETED.value,
            total_amount=Decimal('90.00'),
        )
        invoice = Invoice.objects.create(
            client=self.customer,
            amount=Decimal('90.00'),
            identifier='SER-HIDDEN',
            folio='FOL-HIDDEN',
        )
        InvoiceOrderLink.objects.create(invoice=invoice, order=order)

        response = self.client.get(reverse('clients:detail', args=[self.customer.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context['client_invoices']), [])
        self.assertNotContains(response, 'SER-HIDDEN')
        self.assertNotContains(response, 'Facturas')

    def test_branch_detail_lists_corporate_issued_invoice_linked_to_branch_order(self) -> None:
        corporate = Client.objects.create(
            name='Corporativo fiscal',
            type='corporate',
            requires_billing=True,
            active=True,
        )
        branch = Client.objects.create(
            name='Sucursal facturada',
            type='branch',
            corporate=corporate,
            requires_billing=True,
            active=True,
        )
        order = Order.objects.create(
            client=branch,
            status=OrderStatus.COMPLETED.value,
            total_amount=Decimal('210.00'),
        )
        invoice = Invoice.objects.create(
            client=corporate,
            amount=Decimal('210.00'),
            identifier='SER-CORP',
            folio='FOL-BRANCH',
            emmited_at=timezone.localdate(),
        )
        InvoiceOrderLink.objects.create(invoice=invoice, order=order)

        response = self.client.get(reverse('clients:detail', args=[branch.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertIn(invoice, list(response.context['client_invoices']))
        self.assertContains(response, 'SER-CORP')
        self.assertContains(response, 'Corporativo fiscal')
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
python manage.py test clients.tests.ClientDetailOrderActionsTests -q
```

Expected: FAIL because `client_invoices` is missing from the context and the template does not render the invoice section.

- [ ] **Step 3: Add invoice context helper**

In `clients/views.py`, add the import:

```python
from django.db.models import QuerySet
```

Add this helper near the other client detail helpers:

```python
def _get_client_detail_invoices(client: Client) -> QuerySet:
    """Return invoices linked to orders owned by this client."""
    from invoice.models import Invoice

    if not client.requires_billing:
        return Invoice.objects.none()

    return (
        Invoice.objects.filter(invoice_links__order__client=client)
        .select_related('client')
        .prefetch_related('invoice_links__order__payments')
        .distinct()
        .order_by('-date', '-id')
    )
```

In `detail()`, add:

```python
    client_invoices = _get_client_detail_invoices(client)
```

Add to the context:

```python
        'client_invoices': client_invoices,
```

- [ ] **Step 4: Render invoice table**

In `clients/templates/client_detail.html`, add a card above the "Ventas Recientes" card inside the right column:

```django
      {% if client.requires_billing %}
      <div id="client-invoices" class="card mb-4">
        <div class="card-header section-header d-flex justify-content-between align-items-center">
          <h5 class="mb-0"><i class="fas fa-file-invoice-dollar me-2"></i>Facturas</h5>
          <small class="text-muted">
            {% if client_invoices %}
              {{ client_invoices|length }} registradas
            {% else %}
              Sin facturas
            {% endif %}
          </small>
        </div>
        <div class="card-body">
          {% if client_invoices %}
            <div class="table-responsive">
              <table class="table table-hover">
                <thead class="table-light">
                  <tr>
                    <th>ID</th>
                    <th>Cliente fiscal</th>
                    <th>Serie</th>
                    <th>Folio</th>
                    <th>Emisión</th>
                    <th>Monto</th>
                    <th>Pagado</th>
                    <th>Pendiente</th>
                    <th>Acciones</th>
                  </tr>
                </thead>
                <tbody>
                  {% for invoice in client_invoices %}
                    <tr>
                      <td><strong>#{{ invoice.id }}</strong></td>
                      <td>{{ invoice.client.name }}</td>
                      <td><code>{{ invoice.identifier }}</code></td>
                      <td><code>{{ invoice.folio }}</code></td>
                      <td>{{ invoice.emmited_at|date:"d/m/Y"|default:"-" }}</td>
                      <td>${{ invoice.amount|floatformat:2 }}</td>
                      <td>${{ invoice.total_payments|floatformat:2 }}</td>
                      <td class="{% if invoice.pending_amount > 0 %}text-danger fw-bold{% else %}text-success{% endif %}">
                        ${{ invoice.pending_amount|floatformat:2 }}
                      </td>
                      <td>
                        <a href="{% url 'admin_edit_invoice' invoice.id %}" class="btn btn-sm btn-outline-dark">
                          <i class="fas fa-file-invoice"></i>
                        </a>
                      </td>
                    </tr>
                  {% endfor %}
                </tbody>
              </table>
            </div>
          {% else %}
            <p class="text-muted mb-0">No hay facturas vinculadas a las ventas de este cliente.</p>
          {% endif %}
        </div>
      </div>
      {% endif %}
```

- [ ] **Step 5: Run tests to verify they pass**

Run:

```bash
python manage.py test clients.tests.ClientDetailOrderActionsTests -q
```

Expected: PASS.

### Task 2: Overdue Payment Invoice Column

**Files:**
- Modify: `clients/tests.py`
- Modify: `clients/templates/client_detail.html`

**Interfaces:**
- Consumes: `pending_payment_data.overdue_orders` where each order has prefetched `invoice_links__invoice`
- Produces: an optional invoice link in the overdue table

- [ ] **Step 1: Write failing tests for overdue invoice links**

Add helper to `ClientDetailOrderActionsTests`:

```python
    def _create_overdue_credit_order(self, *, total: Decimal = Decimal('100.00')) -> Order:
        self.customer.requires_billing = True
        self.customer.can_pay_with_credit = True
        self.customer.credit_limit = Decimal('1000.00')
        self.customer.save(
            update_fields=[
                'requires_billing',
                'can_pay_with_credit',
                'credit_limit',
                'updated_at',
            ],
        )
        ClientCreditConfig.objects.create(
            client=self.customer,
            payment_term_type='monthly_cutoff',
            cutoff_day='1',
        )
        order = Order.objects.create(
            client=self.customer,
            status=OrderStatus.COMPLETED.value,
            total_amount=total,
            type='credito',
        )
        Order.objects.filter(pk=order.pk).update(
            order_date=timezone.now() - timedelta(days=60),
        )
        CreditTransaction.objects.create(
            client=self.customer,
            amount=total,
            transaction_type='purchase',
            reference_order=order,
        )
        return Order.objects.get(pk=order.pk)
```

Add tests:

```python
    def test_overdue_payments_table_links_invoiced_order_to_invoice(self) -> None:
        order = self._create_overdue_credit_order()
        invoice = Invoice.objects.create(
            client=self.customer,
            amount=Decimal('100.00'),
            identifier='SER-OVERDUE',
            folio='FOL-OVERDUE',
            emmited_at=timezone.localdate() - timedelta(days=45),
        )
        InvoiceOrderLink.objects.create(invoice=invoice, order=order)

        response = self.client.get(reverse('clients:detail', args=[self.customer.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '¡Atención! Pagos Vencidos')
        self.assertContains(response, '<th>Factura</th>')
        self.assertContains(
            response,
            f'href="{reverse("admin_edit_invoice", args=[invoice.pk])}"',
        )
        self.assertContains(response, f'#{invoice.pk}')

    def test_overdue_payments_table_shows_dash_for_order_without_invoice(self) -> None:
        self._create_overdue_credit_order()

        response = self.client.get(reverse('clients:detail', args=[self.customer.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '¡Atención! Pagos Vencidos')
        self.assertContains(response, '<th>Factura</th>')
        self.assertContains(response, '<span class="text-muted">-</span>')
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
python manage.py test clients.tests.ClientDetailOrderActionsTests -q
```

Expected: FAIL because the overdue table does not have the `Factura` column.

- [ ] **Step 3: Add the overdue invoice column**

In `clients/templates/client_detail.html`, add the header after `Monto Pendiente`:

```django
                <th>Factura</th>
```

Add the row cell after the pending amount:

```django
                <td>
                  {% for invoice_link in overdue_order.invoice_links.all %}
                    <a href="{% url 'admin_edit_invoice' invoice_link.invoice.id %}" class="btn btn-sm btn-outline-dark">
                      #{{ invoice_link.invoice.id }}
                    </a>
                  {% empty %}
                    <span class="text-muted">-</span>
                  {% endfor %}
                </td>
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
python manage.py test clients.tests.ClientDetailOrderActionsTests -q
```

Expected: PASS.

- [ ] **Step 5: Run broader verification**

Run:

```bash
python manage.py test clients -q
```

Expected: PASS.
