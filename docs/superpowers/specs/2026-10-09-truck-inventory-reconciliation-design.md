# Truck Inventory Reconciliation Design

## Purpose

Build a basic operational prototype for tracking product and container movement on delivery trucks. The goal is to help administration reconcile what each truck physically moved against reported sales and returned empty containers.

The prototype should make the driver's capture fast and make the administrative review visible in the existing daily report.

## Operating Model

The driver should not need to enter a route first. The primary entry point is a direct button from the home screen:

`Inventario de camioneta`

If the logged-in driver has one active route for today, the form opens with that route and truck selected. If more than one route is available, the driver selects route/truck first. Staff users can select date, truck, and route.

The route detail page may show a secondary link and the current inventory status, but the main flow starts from home.

## Scope

Add one truck inventory session per route, truck, and service date. A session represents the physical count for one truck workday.

The first version captures aggregate counts per product, not one transaction per returned container. This keeps the driver workflow simple and supports the main reconciliation question:

`Did the truck report sales and containers consistently with what physically left and returned?`

Per-client container accountability is intentionally outside this prototype. It can be added later as a separate client container ledger for cases like loans, deposits, and client-specific returns.

## Data Model

Create route-owned tenant data for inventory sessions and lines.

### Truck Inventory Session

Fields:

- `route`
- `transportation`
- `service_date`
- `status`
- `opened_by`
- `closed_by`
- `opened_at`
- `closed_at`
- `notes`
- timestamps and soft delete fields through `TimeStampedModel`

Status values:

- `Abierta`
- `Cerrada`

Enforce one active session per `route + transportation + service_date`.

### Truck Inventory Line

Each line belongs to one session and one product.

Fields:

- `session`
- `product`
- `full_loaded`
- `full_returned`
- `empty_returned`
- `expected_sales`
- `reported_sales`
- `sales_difference`
- `missing_containers`
- `notes`
- timestamps and soft delete fields through `TimeStampedModel`

The line stores raw counts and denormalized calculated results at save/close time so reports remain stable even if later orders are edited.

Calculations:

- `expected_sales = full_loaded - full_returned`
- `sales_difference = expected_sales - reported_sales`
- `missing_containers = expected_sales - empty_returned`

Counts cannot be negative. Returned full units cannot exceed loaded full units.

## Reported Sales Source

Reported sales are calculated from completed, non-cancelled orders for the same route/truck service date.

For the prototype, route attribution uses the active route/session context:

- If an order is linked through `RouteClientOrder`, count it for that route.
- If route linkage is missing, count orders created by the driver assigned to the truck on that date when available.
- Staff can manually review differences in the daily report if attribution is incomplete.

This keeps the prototype useful with existing order data while avoiding a broad order model rewrite.

## Driver/Admin Form

Create a single operational form:

- service date
- route
- truck
- repeated product rows
- full units loaded in the morning
- full units returned at the end
- empty containers returned at the end
- notes

For drivers, route/truck fields are prefilled and limited to their assigned work. For staff, they are selectable.

The same form can be saved during the day and closed at the end. Closing recalculates all line results and records `closed_by` and `closed_at`.

The form is optimized for garrafon operations but supports multiple products from the beginning.

## Daily Report Integration

Add a truck inventory reconciliation section to the existing `Reporte de Hoy`.

Show one summary per route/truck session:

- route
- truck
- status
- full loaded
- full returned
- empty returned
- expected sales
- reported sales
- sales difference
- missing containers
- notes

Highlight non-zero `sales_difference` or `missing_containers`.

The report is the administrative review surface. The route screen only needs a compact inventory status and link.

## Container Return Operation

The prototype records returned containers as one aggregate count per product at close:

`Regresaron 20 envases vacios`

It does not create one transaction per physical returned container. That level of detail would slow down the driver and belongs to a separate client container ledger if the business needs to answer:

`Which client owes which containers?`

Future client-level ledger events can coexist with the truck session:

- client borrowed containers
- client returned containers
- client paid/lost containers

The daily truck reconciliation can then subtract explained client movements from missing containers.

## Permissions

Drivers can create and update inventory sessions only for their assigned truck/routes.

Staff users can create, edit, close, and review sessions for any route/truck.

All mutating actions require login and CSRF-protected POST requests.

## Screens

Add or update:

- Home screen: direct `Inventario de camioneta` action.
- Inventory form: one route/truck/day capture page.
- Route detail: compact status and link to the current session.
- Reporte de Hoy: administrative reconciliation section.

## Testing

Model and service tests cover:

- one active session per route/truck/date
- expected sales calculation
- sales difference calculation
- missing container calculation
- validation for negative counts
- validation that full returned cannot exceed full loaded
- driver access limited to assigned truck/routes
- staff can select any route/truck
- daily report context includes reconciliation summaries

View tests cover:

- driver home link reaches the inventory form
- driver single-route context preselects route/truck
- staff can open the form with selectable route/truck
- report highlights differences
