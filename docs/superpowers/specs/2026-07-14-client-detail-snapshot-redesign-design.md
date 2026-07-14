# Client Detail Snapshot Redesign Design

## Goal

Redesign `clients/templates/client_detail.html` into a more compact account snapshot without removing important client state. The page should answer:

- Who is this client and can staff act on the account now?
- Is there financial risk that should block or change the next action?
- What is scheduled next for delivery or billing?
- Where can staff review recent sales, payments, invoices, routes, and profile details?

The chosen direction is **Layout A: Snapshot dashboard**. It presents a balanced first-screen snapshot by default and promotes financial risk above everything else when overdue debt exists.

## Current Page Problems

The current page contains the right information, but it presents too many full sections at once:

- Header actions, notes, addresses, financial cards, overdue table, contacts, branches, billing data, billing frequency, routes, invoices, sales, and payments all compete for attention.
- Important current-state signals are spread across several vertical sections.
- Dense history tables dominate the page even when staff only need the current account state.
- Slow-changing profile data, such as contacts, fiscal data, and billing rules, takes the same visual weight as urgent financial or route status.

## Information Hierarchy

The design uses this hierarchy:

1. **Urgent financial risk**, only when it exists.
2. **Balanced account snapshot**, always visible near the top in one compact row.
3. **Tabbed drill-down content** for sales, payments, invoices, routes, and profile.

Financial risk does not permanently dominate the design. It is promoted only when `pending_payment_data.total_overdue_amount > 0`.

## Top Snapshot

### Header

The header remains compact:

- client name,
- active/inactive badge,
- client type badge,
- corporate relationship badge when present,
- primary actions.

Primary action order:

1. `Nuevo pedido`
2. `Reporte de crédito`
3. `Editar`
4. `Volver`

The page should avoid a large block of buttons. Secondary actions can be grouped or visually reduced if necessary.
All header actions use a uniform soft neutral filled style so the content hierarchy, not button color, carries priority.
Client account operations should not crowd the header. `Gestionar saldo` lives in the `Saldo prepago` tile and `Gestionar crédito` lives in the `Crédito` tile.

### Risk Alert

When the client has overdue payments, render a red alert above the metric cards.

Alert content:

- total overdue amount,
- maximum days overdue,
- overdue order count when available,
- concise operational warning.

Alert CTA:

- label: `Ver reporte de crédito`
- destination: existing `report:client_credit_report` route for the client.

Do not label this CTA `Ver detalles`, because that hides where the user will go.

### Metric Cards

Use a stable five-card snapshot in one desktop row:

1. `Saldo prepago`
   - value: `client.balance`
   - state: available, none, or negative.
   - action: `Gestionar saldo`.
2. `Deuda actual`
   - value: `client.current_debt`
   - state: no debt, pending, or overdue.
3. `Crédito`
   - value: usage percentage when credit is enabled.
   - supporting text: available credit and credit limit.
   - fallback: `Sin crédito habilitado` when the client has no credit limit.
   - action: `Gestionar crédito`.
4. `Próxima visita`
   - value: next scheduled visit or route day when available.
   - fallback: no assigned route.
5. `Facturación`
   - value: next billing date when configured.
   - supporting text: pending invoice count.
   - fallback: no date, or not applicable when billing is disabled.

Credit due-date details remain visible through the risk alert and credit report. When there is no route information, the fourth card should still render with a clear empty state instead of disappearing and shifting the layout.
The tiles use subtle tinted backgrounds by state to improve scanability without turning the header actions into competing primary buttons.

Contact, delivery, and full fiscal details should not appear as separate cards in the first viewport. They remain available in `Perfil`, `Facturas`, and `Rutas`.

## Tabbed Content

The lower section uses tabs so dense data remains available without rendering as several stacked full sections. The page opens on `Ventas`; the separate `Actividad` timeline is intentionally removed.

### Dedicated Tabs

Keep richer data in dedicated tabs:

- `Ventas`: current recent sales table and pagination.
- `Pagos`: current payment/balance/credit transaction table and pagination.
- `Facturas`: current invoice table shown only for clients requiring billing.
- `Rutas`: route assignment, upcoming visits, and recent completed deliveries.
- `Perfil`: contacts, addresses, fiscal data, billing frequency, branches, and notes.

The existing content should be reorganized, not removed.

### Empty States

Each tab needs a compact empty state:

- no sales,
- no transactions,
- no invoices,
- no routes,
- no contacts or addresses.

Empty states should be short and actionable only when there is a meaningful next action.

## Data Flow

The current `clients.views.detail` context already supplies most data needed by the design:

- `client`
- `orders`
- `all_payment_data`
- `contacts`
- `addresses`
- `branches`
- `billing_data`
- `billing_frequency`
- `route_clients`
- `upcoming_route_orders`
- `recent_completed_routes`
- `client_invoices`
- `pending_payment_data`
- `debt_percentage`

Implementation should keep view logic thin by extracting snapshot-specific composition into typed helpers or a service module if the view starts growing.

Recommended additions:

- a small snapshot context object for top cards and context strips,
- an activity feed builder that merges existing order, payment, invoice, and route data into normalized timeline rows.

Because the activity feed spans multiple aggregates, it belongs in a service/helper layer rather than in model methods.

## Error Handling

The page should not break or shift dramatically when optional data is missing.

Rules:

- Missing contact: show `Sin contacto principal`.
- Missing delivery address: show `Sin dirección activa`.
- Missing route: show `Sin ruta asignada`.
- Missing billing frequency: show `Sin frecuencia configurada`.
- Missing invoice date: show `-`.
- No credit limit: show `Sin crédito habilitado` and avoid dividing by zero.
- Multiple invoice links for one order: render the links that exist.

## Responsiveness

Desktop:

- header and actions share one row,
- four metric cards render in one row when width allows,
- context strips render in one row,
- tabs occupy the full width below.

Tablet:

- metric cards render two per row,
- context strips may stack or use two columns.

Mobile:

- header actions wrap below the client name,
- metric cards render one or two per row depending on width,
- tabs scroll horizontally,
- tables remain responsive using existing Bootstrap table wrappers.

## Testing

Add focused tests around rendered behavior rather than pixel layout:

- client with overdue payments renders the risk alert and `Ver reporte de crédito` link.
- client without overdue payments does not render the risk alert.
- top snapshot renders balance, debt, credit, and route/empty route states.
- client requiring billing renders the `Facturas` tab and linked invoices.
- client not requiring billing does not render invoice content.
- corporate client still renders branch data in the `Perfil` tab.
- pagination links for sales and payments still preserve the relevant anchors or tab targets.
- existing credit due date behavior remains covered.

Manual visual verification should check desktop and mobile widths because the redesign mainly changes hierarchy and density.

## Out Of Scope

This design does not add new payment collection workflows, change credit business rules, change invoice ownership logic, or redesign the credit report page.

The overdue alert links to the existing credit report screen. A separate `Cobrar` action can be designed later if there is a direct collection workflow with clear permission and transaction behavior.
