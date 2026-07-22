# Invoice Fiscal Owner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make invoices issued to the fiscal owner while linked orders keep operational ownership, payment state, debt, and overdue rules.

**Architecture:** Keep the existing `Invoice.client` database field and treat it as the fiscal client. Add service-level fiscal owner helpers and validation, then update invoice creation, order eligibility, admin/dashboard flows, and tests to use fiscal-owner semantics where invoices are edited or generated.

**Tech Stack:** Django 5.2, Django ORM/querysets, Django admin/forms, `python manage.py test`.

## Global Constraints

- No schema migration is required for the first implementation.
- `Invoice.client` means fiscal client / issued-to client.
- Branch order debt, payments, and overdue logic stay on `order.client`.
- An invoice is paid only when all linked orders are paid.
- Branch orders can be linked to a corporate invoice when `order.client.corporate == invoice.client`.
- Orders from different fiscal owners cannot be linked to the same invoice.
- Keep domain orchestration in services and managers/querysets, not views.
- Add type hints to new function signatures.

---

## File Structure

- Modify `invoice/services.py`: fiscal owner helper, link validation, create-from-orders behavior, invoiceable order scope.
- Modify `orders/models.py`: queryset support for unbilled completed orders by fiscal owner.
- Modify `invoice/forms.py`: pass fiscal-owner scope when editing an invoice and validate links through services.
- Modify `invoice/admin.py`: inline order queryset uses fiscal-owner scope.
- Modify `invoice/views.py`: custom invoice edit page uses fiscal-owner scope and GET scope support.
- Modify `orders/admin.py`: remove exact-client restriction for invoice creation and rely on same-fiscal-owner validation.
- Modify `orders/views.py`: keep dashboard bulk action aligned with the service result and fiscal owner copy.
- Modify `invoice/tests.py`: service/form/view coverage for fiscal-owner behavior and adjust legacy tests to create corporate clients when they mean standalone customers.
- Modify `orders/tests.py`: dashboard bulk action coverage for multi-branch same-corporate and different-corporate rejection.

## Task 1: Fiscal Owner Service Contract

**Files:**
- Modify: `invoice/services.py`
- Modify: `invoice/tests.py`

**Interfaces:**
- Produces: `get_invoice_fiscal_owner(client: Client) -> Client`
- Produces: `validate_order_can_link_to_invoice(invoice: Invoice, order: Order, exclude_invoice_order_link_id: Optional[int] = None) -> None`

- [ ] **Step 1: Write failing service tests**

Add tests to `CreateInvoiceFromOrdersServiceTests`:

```python
def test_branch_order_invoice_is_issued_to_corporate(self):
    from invoice.services import create_invoice_from_orders

    branch = Client.objects.create(
        name='Client A Branch',
        type='branch',
        corporate=self.client_a,
    )
    order = self._completed_order(branch, '50.00')

    invoice = create_invoice_from_orders(orders=[order], client=branch)

    self.assertEqual(invoice.client, self.client_a)
    self.assertEqual(invoice.invoice_links.get().order, order)

def test_multi_branch_invoice_is_issued_to_shared_corporate(self):
    from invoice.services import create_invoice_from_orders

    branch_one = Client.objects.create(name='Branch One', type='branch', corporate=self.client_a)
    branch_two = Client.objects.create(name='Branch Two', type='branch', corporate=self.client_a)
    order_one = self._completed_order(branch_one, '25.00')
    order_two = self._completed_order(branch_two, '35.00')

    invoice = create_invoice_from_orders(orders=[order_one, order_two], client=branch_one)

    self.assertEqual(invoice.client, self.client_a)
    self.assertEqual(invoice.amount, Decimal('60.00'))

def test_rejects_branch_without_corporate(self):
    from django.core.exceptions import ValidationError
    from invoice.services import create_invoice_from_orders

    branch = Client.objects.create(name='Orphan Branch', type='branch')
    order = self._completed_order(branch, '10.00')

    with self.assertRaisesMessage(ValidationError, 'corporativo'):
        create_invoice_from_orders(orders=[order], client=branch)
```

- [ ] **Step 2: Run tests to verify failure**

Run: `python manage.py test invoice.tests.CreateInvoiceFromOrdersServiceTests -q`

Expected: failures showing the invoice is still created for the branch or orphan branches are not rejected consistently.

- [ ] **Step 3: Implement fiscal owner helper and update create flow**

In `invoice/services.py`, replace `_get_invoice_billing_owner()` with:

```python
def get_invoice_fiscal_owner(client: Client) -> Client:
    """Return the client whose fiscal data must be used for invoices."""
    if client.type == 'branch':
        if client.corporate_id is None:
            raise ValidationError(
                f'El cliente "{client.name}" no puede facturarse sin un cliente corporativo asociado.'
            )
        return client.corporate
    return client


def _get_invoice_billing_owner(client: Client) -> Client:
    """Backward-compatible alias for older billing terminology."""
    return get_invoice_fiscal_owner(client)
```

Update `validate_client_invoice_generation_requirements()` to call `get_invoice_fiscal_owner(client)`.

Update `create_invoice_from_orders()` so it resolves fiscal owners from the selected orders and creates the invoice for that owner:

```python
fiscal_owners = {get_invoice_fiscal_owner(order.client) for order in orders}
if len(fiscal_owners) > 1:
    raise ValidationError("Todos los pedidos deben pertenecer al mismo cliente corporativo.")
fiscal_owner = next(iter(fiscal_owners))
validate_client_invoice_generation_requirements(fiscal_owner)
...
invoice = Invoice.objects.create(
    client=fiscal_owner,
    amount=total,
    auto_amount=True,
    identifier=f'BORRADOR-{short_id}',
    folio=f'BORRADOR-{short_id}',
)
```

- [ ] **Step 4: Run service tests**

Run: `python manage.py test invoice.tests.CreateInvoiceFromOrdersServiceTests -q`

Expected: PASS.

## Task 2: Invoiceable Orders By Fiscal Owner

**Files:**
- Modify: `orders/models.py`
- Modify: `invoice/services.py`
- Modify: `invoice/tests.py`

**Interfaces:**
- Consumes: `get_invoice_fiscal_owner(client: Client) -> Client`
- Produces: `Order.objects.unbilled_for_fiscal_owner(fiscal_owner, exclude_order_id=None)`
- Produces: `get_invoiceable_orders_for_client(client, include_order_id=None, as_dict=False, scope='exact')`

- [ ] **Step 1: Write failing queryset/service tests**

Add tests to `GetInvoiceableOrdersServiceTests`:

```python
def test_fiscal_owner_scope_includes_corporate_and_branch_orders(self):
    from invoice.services import get_invoiceable_orders_for_client

    corporate = Client.objects.create(name='Fiscal Corp', type='corporate')
    branch = Client.objects.create(name='Fiscal Branch', type='branch', corporate=corporate)
    corporate_order = Order.objects.create(client=corporate, total_amount=Decimal('10.00'), status='COMPLETED')
    branch_order = Order.objects.create(client=branch, total_amount=Decimal('20.00'), status='COMPLETED')

    qs = get_invoiceable_orders_for_client(client=corporate, scope='fiscal_owner')

    self.assertIn(corporate_order, qs)
    self.assertIn(branch_order, qs)

def test_exact_scope_keeps_existing_single_client_filter(self):
    from invoice.services import get_invoiceable_orders_for_client

    corporate = Client.objects.create(name='Exact Corp', type='corporate')
    branch = Client.objects.create(name='Exact Branch', type='branch', corporate=corporate)
    branch_order = Order.objects.create(client=branch, total_amount=Decimal('20.00'), status='COMPLETED')

    qs = get_invoiceable_orders_for_client(client=corporate, scope='exact')

    self.assertNotIn(branch_order, qs)
```

- [ ] **Step 2: Run tests to verify failure**

Run: `python manage.py test invoice.tests.GetInvoiceableOrdersServiceTests -q`

Expected: FAIL because `scope` and `unbilled_for_fiscal_owner` are not implemented.

- [ ] **Step 3: Implement fiscal-owner order queryset**

In `orders/models.py`, add to `OrderQuerySet`:

```python
def unbilled_for_fiscal_owner(self, fiscal_owner, exclude_order_id=None):
    fiscal_owner_id = fiscal_owner.pk if hasattr(fiscal_owner, 'pk') else fiscal_owner
    billable_filter = Q(
        status=OrderStatus.COMPLETED.value,
        invoice_links__isnull=True,
    )
    owner_filter = Q(client_id=fiscal_owner_id) | Q(client__corporate_id=fiscal_owner_id)

    if exclude_order_id:
        qs = self.filter(owner_filter).filter(billable_filter | Q(pk=exclude_order_id))
    else:
        qs = self.filter(owner_filter).filter(billable_filter)

    return qs.distinct().order_by('-order_date')
```

Add the same delegating method to `OrderManager`.

In `invoice/services.py`, update `get_invoiceable_orders_for_client()` signature and branch:

```python
def get_invoiceable_orders_for_client(
    client: Client,
    include_order_id: Optional[int] = None,
    as_dict: bool = False,
    scope: str = 'exact',
) -> List:
    if scope == 'fiscal_owner':
        fiscal_owner = get_invoice_fiscal_owner(client)
        orders = Order.objects.unbilled_for_fiscal_owner(
            fiscal_owner=fiscal_owner,
            exclude_order_id=include_order_id,
        )
    else:
        orders = Order.objects.unbilled_for_client(
            client=client,
            exclude_order_id=include_order_id,
        )
```

- [ ] **Step 4: Run queryset/service tests**

Run: `python manage.py test invoice.tests.GetInvoiceableOrdersServiceTests -q`

Expected: PASS.

## Task 3: Link Validation And Forms

**Files:**
- Modify: `invoice/services.py`
- Modify: `invoice/forms.py`
- Modify: `invoice/admin.py`
- Modify: `invoice/views.py`
- Modify: `invoice/tests.py`

**Interfaces:**
- Consumes: `get_invoice_fiscal_owner(client: Client) -> Client`
- Consumes: `get_invoiceable_orders_for_client(..., scope='fiscal_owner')`
- Produces: service-enforced linking rules for `add_order_to_invoice()`

- [ ] **Step 1: Write failing form/service tests**

Add tests to `BillingOrderAdminFormTests`:

```python
def test_invoice_for_corporate_can_select_branch_order(self):
    self.client_a.type = 'corporate'
    self.client_a.save(update_fields=['type', 'updated_at'])
    branch = Client.objects.create(name='Client A Branch', type='branch', corporate=self.client_a)
    invoice = Invoice.objects.create(
        client=self.client_a,
        amount=Decimal('100.00'),
        identifier='SER-BR-001',
        folio='FOL-BR-001',
    )
    branch_order = Order.objects.create(client=branch, total_amount=Decimal('40.00'), status='COMPLETED')

    form = InvoiceOrderLinkAdminForm(invoice=invoice)

    self.assertIn(branch_order, form.fields['order'].queryset)

def test_form_rejects_order_from_different_fiscal_owner(self):
    from invoice.services import add_order_to_invoice
    from django.core.exceptions import ValidationError

    other_corporate = Client.objects.create(name='Other Corporate', type='corporate')
    other_branch = Client.objects.create(name='Other Branch', type='branch', corporate=other_corporate)
    invoice = Invoice.objects.create(
        client=self.client_a,
        amount=Decimal('100.00'),
        identifier='SER-BR-002',
        folio='FOL-BR-002',
    )
    other_order = Order.objects.create(client=other_branch, total_amount=Decimal('40.00'), status='COMPLETED')

    with self.assertRaisesMessage(ValidationError, 'cliente fiscal'):
        add_order_to_invoice(invoice=invoice, order=other_order)
```

- [ ] **Step 2: Run tests to verify failure**

Run: `python manage.py test invoice.tests.BillingOrderAdminFormTests -q`

Expected: FAIL because admin form still uses exact client scope and link validation does not check fiscal owner.

- [ ] **Step 3: Implement validation and fiscal-owner form scope**

In `invoice/services.py`, add:

```python
def validate_order_can_link_to_invoice(
    invoice: 'invoice.models.Invoice',
    order: Order,
    exclude_invoice_order_link_id: Optional[int] = None,
) -> None:
    from invoice.models import InvoiceOrderLink
    from orders.models import OrderStatus

    existing_links = InvoiceOrderLink.objects.filter(order=order)
    if exclude_invoice_order_link_id:
        existing_links = existing_links.exclude(pk=exclude_invoice_order_link_id)
    if existing_links.exists():
        raise ValidationError(f'El pedido #{order.id} ya esta vinculado a otra factura.')

    if order.status != OrderStatus.COMPLETED.value:
        raise ValidationError(f'Solo se pueden facturar pedidos completados. Pedido #{order.id}.')

    order_fiscal_owner = get_invoice_fiscal_owner(order.client)
    if order_fiscal_owner.pk != invoice.client_id:
        raise ValidationError(
            f'El pedido #{order.id} pertenece a otro cliente fiscal.'
        )
```

Call it at the start of `add_order_to_invoice()` before the amount cap.

In `InvoiceOrderLinkAdminForm.__init__()`, pass `scope='fiscal_owner'`.

In `InvoiceOrderLinkForm`, add `scope = kwargs.pop('scope', 'exact')` and pass it to `get_invoiceable_orders_for_client()`.

In `edit_invoice_admin()`, instantiate `InvoiceOrderLinkForm(client=invoice.client, scope='fiscal_owner')` and call `get_invoiceable_orders_for_client(client=invoice.client, scope='fiscal_owner', as_dict=True)`.

- [ ] **Step 4: Run form/service tests**

Run: `python manage.py test invoice.tests.BillingOrderAdminFormTests invoice.tests.CustomAdminInvoiceViewsTests -q`

Expected: PASS.

## Task 4: Bulk Invoice Creation Entry Points

**Files:**
- Modify: `orders/admin.py`
- Modify: `orders/views.py`
- Modify: `orders/tests.py`

**Interfaces:**
- Consumes: `create_invoice_from_orders(orders: List, client: Client) -> Invoice`
- Consumes: fiscal owner validation inside `invoice.services`

- [ ] **Step 1: Write failing dashboard/admin tests**

Add tests to `OrdersDashboardBulkActionTestCase`:

```python
def test_dashboard_bulk_create_invoice_allows_same_corporate_branches(self) -> None:
    branch_one = Client.objects.create(name='Bulk Branch One', type='branch', corporate=self.customer)
    branch_two = Client.objects.create(name='Bulk Branch Two', type='branch', corporate=self.customer)
    order_one = Order.objects.create(client=branch_one, owner=self.user, status=OrderStatus.COMPLETED.value, total_amount=Decimal('15.00'))
    order_two = Order.objects.create(client=branch_two, owner=self.user, status=OrderStatus.COMPLETED.value, total_amount=Decimal('25.00'))

    response = self.client.post(
        reverse('admin_orders'),
        data={'bulk_action': 'create_invoice', 'selected_orders': [order_one.pk, order_two.pk]},
    )

    self.assertEqual(response.status_code, 302)
    invoice = Invoice.objects.get(client=self.customer)
    self.assertEqual(invoice.amount, Decimal('40.00'))
    self.assertSetEqual(
        set(invoice.invoice_links.values_list('order_id', flat=True)),
        {order_one.pk, order_two.pk},
    )

def test_dashboard_bulk_create_invoice_rejects_different_fiscal_owners(self) -> None:
    branch = Client.objects.create(name='Bulk Branch', type='branch', corporate=self.customer)
    other_branch = Client.objects.create(name='Other Bulk Branch', type='branch', corporate=self.other_customer)
    order_one = Order.objects.create(client=branch, owner=self.user, status=OrderStatus.COMPLETED.value, total_amount=Decimal('15.00'))
    order_two = Order.objects.create(client=other_branch, owner=self.user, status=OrderStatus.COMPLETED.value, total_amount=Decimal('25.00'))

    response = self.client.post(
        reverse('admin_orders'),
        data={'bulk_action': 'create_invoice', 'selected_orders': [order_one.pk, order_two.pk]},
        follow=True,
    )

    self.assertEqual(response.status_code, 200)
    self.assertEqual(Invoice.objects.count(), 0)
    self.assertContains(response, 'mismo cliente corporativo')
```

- [ ] **Step 2: Run tests to verify failure**

Run: `python manage.py test orders.tests.OrdersDashboardBulkActionTestCase -q`

Expected: FAIL because the admin path blocks exact different clients.

- [ ] **Step 3: Update entry point validation**

In `orders/admin.py`, remove the exact `client_ids` length guard in `crear_factura()` and let `create_invoice_from_orders()` validate fiscal ownership. Keep non-completed and already-billed guards.

In `orders/views.py`, keep the same-corporate check or replace it with a call pattern that relies on `create_invoice_from_orders()`. Ensure the success message uses `invoice.client.name`, not `selected_orders[0].client.name`.

```python
messages.success(
    request,
    f'Factura #{invoice.id} creada para {invoice.client.name} por ${invoice.amount}. '
    'Actualiza el identificador y folio antes de emitirla.',
)
```

- [ ] **Step 4: Run dashboard tests**

Run: `python manage.py test orders.tests.OrdersDashboardBulkActionTestCase -q`

Expected: PASS.

## Task 5: Regression Verification

**Files:**
- Test only unless failures expose missed integration points.

**Interfaces:**
- Verifies all previous tasks.

- [ ] **Step 1: Run invoice tests**

Run: `python manage.py test invoice -q`

Expected: PASS.

- [ ] **Step 2: Run order dashboard tests**

Run: `python manage.py test orders.tests.OrdersDashboardBulkActionTestCase -q`

Expected: PASS.

- [ ] **Step 3: Run credit term regression tests**

Run: `python manage.py test clients.tests_credit_terms -q`

Expected: PASS and confirms `invoice_due` remains order-client based.

- [ ] **Step 4: Commit implementation**

```bash
git add invoice/services.py invoice/forms.py invoice/admin.py invoice/views.py orders/models.py orders/admin.py orders/views.py invoice/tests.py orders/tests.py docs/superpowers/plans/2026-07-08-invoice-fiscal-owner.md
git commit -m "Implement invoice fiscal owner behavior"
```
