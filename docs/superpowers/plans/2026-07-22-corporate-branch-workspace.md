# Corporate Branch Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a dedicated server-rendered corporate branch workspace where staff can select a branch and review its summary, orders, and payments.

**Architecture:** Add a focused `clients.services.corporate_branch_service` module that owns date parsing, branch selection, totals, and paginated query composition. Keep `clients.views.corporate_branches` thin, add one `clients:corporate_branches` URL, and render a Bootstrap master-detail template that works without JavaScript.

**Tech Stack:** Django 5.2, Django ORM, Django templates, Bootstrap, Font Awesome, existing `FastTenantTestCase` test infrastructure.

## Global Constraints

- The page is only for `Client.type == "corporate"`.
- Clicking branches and tabs uses normal server-rendered links; no JavaScript data loading.
- Supported query parameters: `branch`, `tab`, `date_from`, `date_to`, `orders_page`, `payments_page`.
- Default date range is the current month.
- Default tab is `summary`.
- Order lists include pending, completed, and cancelled non-deleted orders.
- Sales totals exclude cancelled orders.
- Payment totals include completed payments and exclude `pending_credit` placeholder payments.
- Payment ownership is `Payment.client == selected_branch`; payment date range applies to `Payment.date`.
- Corporate totals include all branches under the corporate, not the corporate client's own orders.
- Keep orchestration out of templates; templates render prepared context.
- Do not change credit rules, invoice fiscal ownership, payment settlement behavior, or add charts/export.

---

### Task 1: Corporate Branch Workspace Service

**Files:**
- Create: `clients/services/corporate_branch_service.py`
- Modify: `clients/tests.py`

**Interfaces:**
- Produces: `build_corporate_branch_workspace(corporate: Client, params: Mapping[str, str], *, today: date | None = None, orders_per_page: int = 15, payments_per_page: int = 15) -> dict[str, Any]`
- Produces context keys: `corporate`, `date_from`, `date_to`, `active_tab`, `branches`, `selected_branch`, `corporate_summary`, `selected_branch_summary`, `orders_page`, `payments_page`

- [x] **Step 1: Write failing service tests**

Add `CorporateBranchWorkspaceServiceTests` to `clients/tests.py`.

Use fixtures:

```python
self.corporate = Client.objects.create(name='Corporativo Agua Norte', type='corporate')
self.branch_a = Client.objects.create(name='Sucursal A', type='branch', corporate=self.corporate, current_debt=Decimal('30.00'), active=True)
self.branch_b = Client.objects.create(name='Sucursal B', type='branch', corporate=self.corporate, current_debt=Decimal('70.00'), active=True)
self.other_corporate = Client.objects.create(name='Corporativo Otro', type='corporate')
self.other_branch = Client.objects.create(name='Sucursal Externa', type='branch', corporate=self.other_corporate, active=True)
```

Create orders in July 2026:

```python
Order.objects.create(client=self.branch_a, status=OrderStatus.COMPLETED.value, total_amount=Decimal('100.00'), order_date=timezone.make_aware(datetime(2026, 7, 5, 9, 0)))
Order.objects.create(client=self.branch_a, status=OrderStatus.PENDING.value, total_amount=Decimal('50.00'), order_date=timezone.make_aware(datetime(2026, 7, 6, 9, 0)))
Order.objects.create(client=self.branch_a, status=OrderStatus.CANCELLED.value, total_amount=Decimal('999.00'), order_date=timezone.make_aware(datetime(2026, 7, 7, 9, 0)))
Order.objects.create(client=self.branch_b, status=OrderStatus.COMPLETED.value, total_amount=Decimal('200.00'), order_date=timezone.make_aware(datetime(2026, 7, 8, 9, 0)))
```

Create payments:

```python
Payment.objects.create(client=self.branch_a, order=branch_a_completed, amount=Decimal('80.00'), method='cash', status='completed')
Payment.objects.create(client=self.branch_a, order=branch_a_pending, amount=Decimal('50.00'), method='pending_credit', status='pending')
Payment.objects.create(client=self.branch_b, order=branch_b_completed, amount=Decimal('200.00'), method='bank_transfer', status='completed')
```

Tests:

```python
def test_build_workspace_defaults_to_first_active_branch_and_current_month(self) -> None:
    context = build_corporate_branch_workspace(self.corporate, {}, today=date(2026, 7, 22))
    self.assertEqual(context['selected_branch'], self.branch_a)
    self.assertEqual(context['active_tab'], 'summary')
    self.assertEqual(context['date_from'], date(2026, 7, 1))
    self.assertEqual(context['date_to'], date(2026, 7, 31))

def test_build_workspace_summarizes_branch_orders_and_payments(self) -> None:
    context = build_corporate_branch_workspace(self.corporate, {'branch': str(self.branch_a.pk)}, today=date(2026, 7, 22))
    self.assertEqual(context['corporate_summary']['total_orders'], 4)
    self.assertEqual(context['corporate_summary']['total_sales'], Decimal('350.00'))
    self.assertEqual(context['corporate_summary']['total_payments'], Decimal('280.00'))
    self.assertEqual(context['corporate_summary']['total_current_debt'], Decimal('100.00'))
    self.assertEqual(context['selected_branch_summary']['order_count'], 3)
    self.assertEqual(context['selected_branch_summary']['sales_total'], Decimal('150.00'))
    self.assertEqual(context['selected_branch_summary']['payment_total'], Decimal('80.00'))

def test_build_workspace_ignores_branch_id_from_other_corporate(self) -> None:
    context = build_corporate_branch_workspace(self.corporate, {'branch': str(self.other_branch.pk)}, today=date(2026, 7, 22))
    self.assertEqual(context['selected_branch'], self.branch_a)
```

- [x] **Step 2: Run tests to verify RED**

Run:

```bash
.venv/bin/python manage.py test clients.tests.CorporateBranchWorkspaceServiceTests
```

Expected: fail because `clients.services.corporate_branch_service` does not exist.

- [x] **Step 3: Implement service**

Create dataclasses:

```python
@dataclass(frozen=True)
class BranchSummary:
    branch: Client
    order_count: int
    sales_total: Decimal
    payment_total: Decimal
    current_debt: Decimal
    cancelled_order_count: int
    cancelled_order_amount: Decimal
    is_selected: bool
    url: str
```

Use helper functions:

```python
def _resolve_date_range(params: Mapping[str, str], *, today: date) -> tuple[date, date]
def _resolve_active_tab(raw_tab: str | None) -> str
def _resolve_selected_branch(branches: Sequence[Client], raw_branch_id: str | None) -> Client | None
def _paginate(items: Any, page_number: str | None, *, per_page: int) -> Page[Any]
```

Return a dict with only prepared values. Use `Sum(..., filter=...)`, `Count(...)`, `Coalesce`, and `Decimal('0.00')` defaults for aggregates.

- [x] **Step 4: Run tests to verify GREEN**

Run:

```bash
.venv/bin/python manage.py test clients.tests.CorporateBranchWorkspaceServiceTests
```

Expected: all service tests pass.

---

### Task 2: Route, View, And Template Rendering

**Files:**
- Modify: `clients/urls.py`
- Modify: `clients/views.py`
- Modify: `clients/templates/client_detail.html`
- Create: `clients/templates/corporate_branch_workspace.html`
- Modify: `clients/tests.py`

**Interfaces:**
- Consumes: `build_corporate_branch_workspace(...) -> dict[str, Any]`
- Produces: `clients:corporate_branches`
- Produces view: `corporate_branches(request: HttpRequest, pk: int) -> HttpResponse`

- [x] **Step 1: Write failing view/template tests**

Add `CorporateBranchWorkspaceViewTests` to `clients/tests.py`.

Tests:

```python
def test_corporate_detail_links_to_branch_workspace(self) -> None:
    response = self.client.get(reverse('clients:detail', args=[self.corporate.pk]))
    self.assertContains(response, reverse('clients:corporate_branches', args=[self.corporate.pk]))
    self.assertContains(response, 'Ver sucursales / ventas')

def test_branch_client_cannot_open_branch_workspace(self) -> None:
    response = self.client.get(reverse('clients:corporate_branches', args=[self.branch_a.pk]))
    self.assertEqual(response.status_code, 404)

def test_branch_workspace_renders_selected_branch_orders_and_payments(self) -> None:
    response = self.client.get(
        reverse('clients:corporate_branches', args=[self.corporate.pk]),
        {'branch': self.branch_a.pk, 'tab': 'orders', 'date_from': '2026-07-01', 'date_to': '2026-07-31'},
    )
    self.assertContains(response, 'Sucursal A')
    self.assertContains(response, '#{}'.format(self.branch_a_completed.id))
    self.assertContains(response, '#{}'.format(self.branch_a_pending.id))
    self.assertContains(response, '#{}'.format(self.branch_a_cancelled.id))
    self.assertNotContains(response, '#{}'.format(self.branch_b_completed.id))

def test_branch_workspace_payments_tab_excludes_pending_credit_placeholder(self) -> None:
    response = self.client.get(
        reverse('clients:corporate_branches', args=[self.corporate.pk]),
        {'branch': self.branch_a.pk, 'tab': 'payments', 'date_from': '2026-07-01', 'date_to': '2026-07-31'},
    )
    self.assertContains(response, '#{}'.format(self.branch_a_payment.id))
    self.assertNotContains(response, 'Crédito Pendiente')
```

- [x] **Step 2: Run tests to verify RED**

Run:

```bash
.venv/bin/python manage.py test clients.tests.CorporateBranchWorkspaceViewTests
```

Expected: fail because the route, view, link, and template do not exist.

- [x] **Step 3: Implement route and view**

In `clients/urls.py` add before the `<int:pk>/` detail route:

```python
path('<int:pk>/branches/', views.corporate_branches, name='corporate_branches'),
```

In `clients/views.py` add:

```python
@login_required
def corporate_branches(request, pk):
    client = get_object_or_404(Client, pk=pk)
    if client.type != 'corporate':
        raise Http404('La vista de sucursales solo aplica a clientes corporativos.')

    context = build_corporate_branch_workspace(client, request.GET)
    return render(request, 'corporate_branch_workspace.html', context)
```

Import `Http404` and `build_corporate_branch_workspace`.

- [x] **Step 4: Implement templates**

Add corporate detail button under the existing header actions, only for corporate clients:

```django
{% if client.type == 'corporate' %}
  <a href="{% url 'clients:corporate_branches' client.pk %}" class="btn btn-outline-info me-2">
    <i class="fas fa-code-branch"></i> Ver sucursales / ventas
  </a>
{% endif %}
```

Create `clients/templates/corporate_branch_workspace.html` with:

- header and back link,
- date range form,
- four corporate summary cards,
- branch list links,
- selected branch summary cards,
- tab links preserving branch and date range,
- responsive orders and payments tables,
- compact empty states.

- [x] **Step 5: Run tests to verify GREEN**

Run:

```bash
.venv/bin/python manage.py test clients.tests.CorporateBranchWorkspaceViewTests
```

Expected: all view/template tests pass.

---

### Task 3: Focused Regression And Cleanup

**Files:**
- Modify as needed after test failures: `clients/services/corporate_branch_service.py`, `clients/views.py`, `clients/templates/corporate_branch_workspace.html`, `clients/templates/client_detail.html`, `clients/tests.py`

**Interfaces:**
- Consumes all Task 1 and Task 2 interfaces.
- Produces a passing focused client suite.

- [x] **Step 1: Run focused service and view tests**

Run:

```bash
.venv/bin/python manage.py test clients.tests.CorporateBranchWorkspaceServiceTests clients.tests.CorporateBranchWorkspaceViewTests
```

Expected: all corporate branch workspace tests pass.

- [x] **Step 2: Run client app tests**

Run:

```bash
.venv/bin/python manage.py test clients
```

Expected: all client tests pass.

- [x] **Step 3: Inspect changed files**

Run:

```bash
git diff --stat
git diff -- clients/services/corporate_branch_service.py clients/views.py clients/urls.py clients/templates/client_detail.html clients/templates/corporate_branch_workspace.html clients/tests.py
```

Expected: changes are limited to the new service, URL/view wiring, templates, tests, and this plan.

- [x] **Step 4: Commit implementation**

Run:

```bash
git add docs/superpowers/plans/2026-07-22-corporate-branch-workspace.md clients/services/corporate_branch_service.py clients/views.py clients/urls.py clients/templates/client_detail.html clients/templates/corporate_branch_workspace.html clients/tests.py
git commit -m "Add corporate branch workspace"
```
