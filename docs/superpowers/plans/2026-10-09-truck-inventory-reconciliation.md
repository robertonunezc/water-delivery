# Truck Inventory Reconciliation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a basic operational truck inventory prototype so drivers/admins capture route truck counts and administration reviews reconciliation in the daily report.

**Architecture:** Keep the feature in the existing `routes` app because sessions belong to route/truck workdays. Add route inventory models and services for calculations, then expose one operational form and reuse the existing dashboard/report surfaces for navigation and review.

**Tech Stack:** Django 5.2, django-tenants, existing `routes`, `orders`, `product`, and `report` apps, Django forms/formsets, Django templates, `FastTenantTestCase`.

**Spec:** `docs/superpowers/specs/2026-10-09-truck-inventory-reconciliation-design.md`

## Global Constraints

- Primary operational entry point is a direct home action named `Inventario de camioneta`.
- Add one active inventory session per `route + transportation + service_date`.
- Session status values are exactly `Abierta` and `Cerrada`.
- Capture aggregate product counts per truck workday, not one transaction per returned container.
- Line calculations are exactly `expected_sales = full_loaded - full_returned`, `sales_difference = expected_sales - reported_sales`, and `missing_containers = expected_sales - empty_returned`.
- Counts cannot be negative; `full_returned` cannot exceed `full_loaded`.
- Drivers can create/update only assigned truck/routes; staff can work with any route/truck.
- Report review belongs in the existing `Reporte de Hoy`.
- Mutating actions require login and CSRF-protected POST requests.

## Review Focus

- Drivers with no assigned active truck should see a clear empty state instead of a broken form.
- Drivers assigned to a truck with no route today should be redirected to a selectable/empty state instead of creating an invalid session.
- Unlinked orders created by the driver and route-linked orders must not be double-counted in reported sales.
- Closed sessions should recalculate and persist line results so later report rendering is stable.
- Product rows with zero counts should not create noisy empty reconciliation lines.

---

### Task 1: Inventory Models And Calculations

**Files:**
- Modify: `routes/models.py`
- Create: `routes/migrations/0013_truck_inventory_session.py`
- Test: `routes/tests.py`

**Interfaces:**
- Produces: `TruckInventorySession.Status.OPEN = 'Abierta'`
- Produces: `TruckInventorySession.Status.CLOSED = 'Cerrada'`
- Produces: `TruckInventorySession.close(user: User | None = None) -> None`
- Produces: `TruckInventoryLine.recalculate() -> None`
- Produces: `TruckInventoryLine.expected_sales: int`
- Produces: `TruckInventoryLine.sales_difference: int`
- Produces: `TruckInventoryLine.missing_containers: int`

- [ ] **Step 1: Write failing model tests**

Add tests to `routes/tests.py`:

```python
def test_inventory_line_recalculates_expected_sales_difference_and_missing_containers(self):
    line = TruckInventoryLine(full_loaded=50, full_returned=10, empty_returned=20, reported_sales=35)
    line.recalculate()
    self.assertEqual(line.expected_sales, 40)
    self.assertEqual(line.sales_difference, 5)
    self.assertEqual(line.missing_containers, 20)

def test_inventory_line_rejects_negative_counts(self):
    line = TruckInventoryLine(full_loaded=-1, full_returned=0, empty_returned=0)
    with self.assertRaises(ValidationError):
        line.full_clean()

def test_inventory_line_rejects_full_returned_greater_than_loaded(self):
    line = TruckInventoryLine(full_loaded=10, full_returned=11, empty_returned=0)
    with self.assertRaises(ValidationError):
        line.full_clean()

def test_only_one_active_inventory_session_per_route_truck_date(self):
    TruckInventorySession.objects.create(route=self.route, transportation=self.transport, service_date=date(2026, 10, 9))
    with self.assertRaises(IntegrityError):
        TruckInventorySession.objects.create(route=self.route, transportation=self.transport, service_date=date(2026, 10, 9))
```

- [ ] **Step 2: Run model tests to verify they fail**

Run: `.venv/bin/python manage.py test routes.tests.RouteTruckInventoryModelTest -v 1`

Expected: FAIL because `TruckInventorySession` and `TruckInventoryLine` do not exist.

- [ ] **Step 3: Implement `TruckInventorySession` in `routes/models.py`**

Add `TruckInventorySession(TimeStampedModel)` with `route`, `transportation`, `service_date`, `status`, `opened_by`, `closed_by`, `opened_at`, `closed_at`, and `notes`. Add a conditional unique constraint on `route`, `transportation`, and `service_date` where `deleted_at__isnull=True`.

- [ ] **Step 4: Implement `TruckInventoryLine` in `routes/models.py`**

Add `TruckInventoryLine(TimeStampedModel)` with `session`, `product`, `full_loaded`, `full_returned`, `empty_returned`, `expected_sales`, `reported_sales`, `sales_difference`, `missing_containers`, and `notes`. Add active uniqueness for `session + product`, implement `clean()`, and implement `recalculate() -> None`.

- [ ] **Step 5: Implement session close behavior**

Implement `TruckInventorySession.close(user: User | None = None) -> None` so it recalculates all active lines, sets `status='Cerrada'`, `closed_by=user`, `closed_at=timezone.now()`, and saves changed fields.

- [ ] **Step 6: Create migration**

Run: `.venv/bin/python manage.py makemigrations routes`

Expected: `routes/migrations/0013_truck_inventory_session.py` is created.

- [ ] **Step 7: Run model tests**

Run: `.venv/bin/python manage.py test routes.tests.RouteTruckInventoryModelTest -v 1`

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add routes/models.py routes/migrations/0013_truck_inventory_session.py routes/tests.py
git commit -m "Add truck inventory models"
```

### Task 2: Inventory Services And Access Rules

**Files:**
- Modify: `routes/services.py`
- Test: `routes/tests.py`

**Interfaces:**
- Consumes: `TruckInventorySession`, `TruckInventoryLine`
- Produces: `get_driver_transportation(user: User) -> Transport | None`
- Produces: `get_inventory_routes_for_user(user: User, service_date: date) -> QuerySet[Route]`
- Produces: `get_or_create_inventory_session(route: Route, transportation: Transport, service_date: date, user: User | None = None) -> TruckInventorySession`
- Produces: `get_reported_sales_by_product(route: Route, transportation: Transport, service_date: date) -> dict[int, int]`
- Produces: `sync_session_reported_sales(session: TruckInventorySession) -> None`
- Produces: `get_daily_inventory_summaries(selected_date: date) -> list[dict[str, Any]]`

- [ ] **Step 1: Write failing service tests**

Add tests to `routes/tests.py`:

```python
def test_driver_inventory_routes_are_limited_to_assigned_truck(self):
    routes = get_inventory_routes_for_user(self.driver_user, self.today)
    self.assertEqual(list(routes), [self.route])

def test_staff_inventory_routes_include_active_routes_for_date(self):
    routes = get_inventory_routes_for_user(self.staff_user, self.today)
    self.assertIn(self.route, routes)

def test_reported_sales_counts_route_linked_and_driver_orders_once(self):
    sales = get_reported_sales_by_product(self.route, self.transport, self.today)
    self.assertEqual(sales[self.product.pk], 3)

def test_sync_session_reported_sales_updates_line_results(self):
    sync_session_reported_sales(self.session)
    self.line.refresh_from_db()
    self.assertEqual(self.line.reported_sales, 3)
    self.assertEqual(self.line.sales_difference, self.line.expected_sales - 3)
```

- [ ] **Step 2: Run service tests to verify they fail**

Run: `.venv/bin/python manage.py test routes.tests.RouteTruckInventoryServiceTest -v 1`

Expected: FAIL with missing service functions.

- [ ] **Step 3: Implement driver access helpers in `routes/services.py`**

`get_driver_transportation(user: User) -> Transport | None` returns the active `Transport` assigned to `user.employee`, or `None`. `get_inventory_routes_for_user(user, service_date)` returns active routes for staff and only active routes for the driver's assigned truck on the weekday for `service_date` for non-staff users.

- [ ] **Step 4: Implement session creation helper**

`get_or_create_inventory_session(route, transportation, service_date, user=None)` validates the route/truck pairing, creates an open session when needed, and sets `opened_by` for new sessions.

- [ ] **Step 5: Implement reported sales aggregation**

`get_reported_sales_by_product(route, transportation, service_date)` collects completed, non-cancelled orders for `service_date` from `RouteClientOrder(route=route, visit_date=service_date)` and unlinked orders owned by the assigned driver user. Aggregate `OrderProduct.quantity` by `product_id`, using distinct order IDs so an order is not counted twice.

- [ ] **Step 6: Implement session sync and daily summaries**

`sync_session_reported_sales(session)` updates each active line's `reported_sales` and recalculates it. `get_daily_inventory_summaries(selected_date)` returns dictionaries with route, truck, status, totals, and line summaries for active sessions on the date.

- [ ] **Step 7: Run service tests**

Run: `.venv/bin/python manage.py test routes.tests.RouteTruckInventoryServiceTest -v 1`

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add routes/services.py routes/tests.py
git commit -m "Add truck inventory services"
```

### Task 3: Operational Inventory Form

**Files:**
- Modify: `routes/forms.py`
- Modify: `routes/views.py`
- Modify: `routes/urls.py`
- Create: `routes/templates/routes/truck_inventory_form.html`
- Test: `routes/tests.py`

**Interfaces:**
- Consumes: Task 2 service functions.
- Produces: `TruckInventorySessionForm`
- Produces: `TruckInventoryLineFormSet`
- Produces: `truck_inventory(request: HttpRequest) -> HttpResponse`
- Produces URL name: `routes:truck_inventory`

- [ ] **Step 1: Write failing form/view tests**

Add tests to `routes/tests.py`:

```python
def test_driver_get_inventory_form_preselects_single_today_route(self):
    self.client.force_login(self.driver_user)
    response = self.client.get(reverse('routes:truck_inventory'))
    self.assertContains(response, self.route.name)
    self.assertContains(response, self.transport.license_plate)

def test_driver_cannot_post_inventory_for_other_truck(self):
    self.client.force_login(self.driver_user)
    response = self.client.post(reverse('routes:truck_inventory'), self._inventory_payload(route=self.other_route, transportation=self.other_transport))
    self.assertEqual(response.status_code, 403)

def test_staff_can_create_inventory_session_from_form(self):
    self.client.force_login(self.staff_user)
    response = self.client.post(reverse('routes:truck_inventory'), self._inventory_payload(route=self.route, transportation=self.transport))
    self.assertRedirects(response, reverse('routes:truck_inventory'))
    self.assertTrue(TruckInventorySession.objects.filter(route=self.route, transportation=self.transport, service_date=self.today).exists())
```

- [ ] **Step 2: Run form/view tests to verify they fail**

Run: `.venv/bin/python manage.py test routes.tests.RouteTruckInventoryViewTest -v 1`

Expected: FAIL with missing form/view/URL.

- [ ] **Step 3: Implement `TruckInventorySessionForm`**

Create a model form for `service_date`, `route`, `transportation`, and `notes`. In `__init__(user: User, service_date: date | None = None, *args, **kwargs)`, limit route/truck choices with Task 2 access helpers for drivers and all active choices for staff.

- [ ] **Step 4: Implement `TruckInventoryLineFormSet`**

Use `inlineformset_factory(TruckInventorySession, TruckInventoryLine, fields=('product', 'full_loaded', 'full_returned', 'empty_returned', 'notes'), extra=3, can_delete=True)`. Style widgets with existing `pg-input` and `pg-select` classes.

- [ ] **Step 5: Implement `truck_inventory()` GET behavior**

For a driver with exactly one available route/truck today, prefill the form and reuse/create the session. For staff, show selectable fields. Render `routes/truck_inventory_form.html` with the session form, line formset, current session, and `can_close`.

- [ ] **Step 6: Implement `truck_inventory()` POST behavior**

Validate access before saving. Save the session and line formset inside `transaction.atomic()`. Drop unsaved line forms where `product`, `full_loaded`, `full_returned`, and `empty_returned` are all empty/zero. If POST has `action=close`, call `sync_session_reported_sales(session)` and `session.close(user=request.user)`.

- [ ] **Step 7: Add URL**

Add `path('inventory/', views.truck_inventory, name='truck_inventory')` to `routes/urls.py`.

- [ ] **Step 8: Create operational template**

Create a mobile-friendly single form with route/truck/date at the top, product count rows, `Guardar` and `Cerrar inventario` buttons, and a clear empty state when no route/truck is available.

- [ ] **Step 9: Run form/view tests**

Run: `.venv/bin/python manage.py test routes.tests.RouteTruckInventoryViewTest -v 1`

Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add routes/forms.py routes/views.py routes/urls.py routes/templates/routes/truck_inventory_form.html routes/tests.py
git commit -m "Add truck inventory form"
```

### Task 4: Dashboard, Route Status, And Daily Report Integration

**Files:**
- Modify: `core/services/dashboard_service.py`
- Modify: `routes/services.py`
- Modify: `routes/views.py`
- Modify: `routes/templates/routes/route_detail.html`
- Modify: `report/views.py`
- Modify: `report/templates/report/breakdown_payment_method.html`
- Test: `routes/tests.py`
- Test: `report/tests.py`

**Interfaces:**
- Consumes: Task 2 daily summary and session helpers.
- Produces: dashboard action with `key='truck_inventory'`
- Produces: `get_route_inventory_status(route: Route, service_date: date) -> dict[str, Any]`
- Produces: report context key `inventory_summaries`

- [ ] **Step 1: Write failing dashboard/report tests**

Add tests:

```python
def test_delivery_dashboard_includes_truck_inventory_action(self):
    context = get_delivery_dashboard_context(user=self.driver_user, today=self.today)
    self.assertTrue(any(action['key'] == 'truck_inventory' for action in context['dashboard_actions']))

def test_route_detail_includes_inventory_status_link(self):
    self.client.force_login(self.driver_user)
    response = self.client.get(reverse('routes:detail', kwargs={'route_id': self.route.pk}))
    self.assertContains(response, 'Inventario de camioneta')

def test_daily_report_includes_inventory_summary(self):
    self.client.force_login(self.staff_user)
    response = self.client.get(reverse('report:breakdown_payment_method'), {'date': self.today.isoformat()})
    self.assertContains(response, 'Cuadre de camionetas')
    self.assertContains(response, self.transport.license_plate)
```

- [ ] **Step 2: Run dashboard/report tests to verify they fail**

Run: `.venv/bin/python manage.py test routes.tests.RouteTruckInventoryIntegrationTest report.tests -v 1`

Expected: FAIL because dashboard/report integration is missing.

- [ ] **Step 3: Add dashboard action**

In `_get_driver_dashboard_actions(current_date)`, add a card before `Ruta del día` with `key='truck_inventory'`, title `Inventario de camioneta`, URL `reverse('routes:truck_inventory')`, icon `fa-boxes-stacked`, variant `primary`, and meta `Conteo de salida y regreso`.

- [ ] **Step 4: Add route inventory status helper**

Implement `get_route_inventory_status(route: Route, service_date: date) -> dict[str, Any]` returning `status`, `session`, `url`, and `has_differences`. Use the current active session for that route/date when present.

- [ ] **Step 5: Render route detail status**

Add a compact route header action in `routes/templates/routes/route_detail.html` linking to `routes:truck_inventory` and showing `Sin captura`, `Abierta`, `Cerrada`, or `Con diferencias`.

- [ ] **Step 6: Add report context**

In `report.views.breakdown_payment_method()`, add `inventory_summaries = route_services.get_daily_inventory_summaries(selected_date)` to the template context.

- [ ] **Step 7: Render report reconciliation section**

In `report/templates/report/breakdown_payment_method.html`, add a `Cuadre de camionetas` section above the payment breakdown. Show one table row per summary with route, truck, status, loaded, full returned, empty returned, expected sales, reported sales, sales difference, and missing containers. Highlight non-zero differences with danger/warning badges.

- [ ] **Step 8: Run integration tests**

Run: `.venv/bin/python manage.py test routes.tests.RouteTruckInventoryIntegrationTest report.tests -v 1`

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add core/services/dashboard_service.py routes/services.py routes/views.py routes/templates/routes/route_detail.html report/views.py report/templates/report/breakdown_payment_method.html routes/tests.py report/tests.py
git commit -m "Integrate truck inventory reporting"
```

### Task 5: Full Verification And Polish

**Files:**
- Review all files changed in Tasks 1-4.

**Interfaces:**
- Consumes: completed implementation.
- Produces: verified prototype branch.

- [ ] **Step 1: Run targeted test suites**

Run: `.venv/bin/python manage.py test routes report core -v 1`

Expected: PASS.

- [ ] **Step 2: Run migration check**

Run: `.venv/bin/python manage.py makemigrations --check --dry-run`

Expected: PASS with no model changes detected.

- [ ] **Step 3: Run style check if available**

Run: `make lint`

Expected: PASS, or document existing unrelated failures.

- [ ] **Step 4: Review git diff**

Run: `git diff --stat HEAD` and `git diff HEAD`

Expected: only truck inventory prototype changes are present.

- [ ] **Step 5: Commit final polish if needed**

If Step 4 shows remaining prototype changes after verification, stage only those listed files and commit them with:

```bash
git commit -m "Polish truck inventory prototype"
```
