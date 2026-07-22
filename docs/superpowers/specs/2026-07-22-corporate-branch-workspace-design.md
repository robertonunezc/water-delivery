# Corporate Branch Workspace Design

## Goal

Add a dedicated server-rendered page for corporate clients that lets staff review branch activity without opening each branch detail page one by one.

The page should answer:

- How are all branches under this corporate performing?
- Which branch needs attention because of pending orders, debt, or missing payments?
- What are the orders for a selected branch?
- What are the payments for a selected branch?

The approved direction is **Option B: Branch workspace** with normal page reloads.

## Current Context

The existing client detail page already supports corporate relationships:

- `Client.type` is either `corporate` or `branch`.
- Branches point to a corporate client through `Client.corporate`.
- Corporate detail pages already receive `branches` and render a simple branch list.
- The client detail page already has order, invoice, route, and payment history sections for one client.

The current branch list is useful for navigation, but it does not show corporate-level branch performance.

## Navigation

Add a button or link on the corporate client detail page:

- Label: `Ver sucursales / ventas`
- Destination: a new dedicated page for the corporate client.

Suggested URL:

- `clients/<int:pk>/branches/`
- route name: `clients:corporate_branches`

This route is valid only for `Client.type == "corporate"`.

If a non-corporate client opens the route, return a clear not-found or redirect response. Prefer `Http404` because the page does not apply to branch clients.

## Page Layout

The page uses a master-detail layout.

### Header

The header shows:

- corporate client name,
- active/inactive badge,
- link back to the corporate client detail,
- date range controls.

Initial date range:

- default to current month,
- allow changing `date_from` and `date_to` through query parameters.

The page should work without JavaScript.

### Corporate Summary

Show compact cards above the workspace:

- total branch sales,
- total branch orders,
- total branch payments,
- total current debt across branches.

These totals include all branches under the corporate, not the corporate client's own orders.

### Left Branch List

The left side lists every branch for the corporate.

Each branch row shows:

- branch name,
- active/inactive status,
- order count in the selected period,
- sales total in the selected period,
- payment total in the selected period,
- current debt.

Each branch row is a normal link to the same page with:

- `?branch=<branch_id>`
- current `date_from`, `date_to`, selected tab, and pagination state reset for the selected branch.

If no branch is selected, select the first active branch by name. If there are no active branches, select the first branch by name.

### Right Branch Detail

The right side displays the selected branch.

Top selected-branch summary:

- sales total,
- order count,
- payment total,
- current debt,
- last order date,
- next route visit when available.

Tabs are normal server-rendered links:

- `Resumen`
- `Ordenes`
- `Pagos`

The active tab is controlled by `?tab=summary`, `?tab=orders`, or `?tab=payments`.

Default tab:

- `Resumen`

## Data Semantics

The `Ordenes` tab must list all non-deleted orders for the selected branch in the selected date range, including pending, completed, and cancelled orders. Cancelled orders remain visible because the user asked for all orders.

Financial totals should avoid counting cancelled orders as active sales:

- `total_branch_orders`: count all non-deleted orders in the selected date range.
- `total_branch_sales`: sum non-cancelled order totals in the selected date range.
- `cancelled_order_count`: optional supporting count for context.
- `cancelled_order_amount`: optional supporting total for context.

Payments should use completed payment records for the selected branch in the selected date range. Pending credit placeholder payments should not be counted as received payments.

Payments are selected with `Payment.client == selected_branch`, and the date range applies to `Payment.date`.

The `Pagos` tab should list actual payment records for the selected branch and, where useful, reuse the same payment-history composition already used by the client detail page. If balance and credit transactions are mixed into the payment history, label them clearly so staff can distinguish a payment from a balance or credit movement.

## Data Flow

Keep orchestration out of the template.

Recommended service/helper:

- `clients/services/corporate_branch_service.py`

Responsibilities:

- validate that the requested client is corporate,
- resolve the selected branch,
- apply the date range,
- build corporate totals across branches,
- build per-branch summary rows,
- build selected-branch summary,
- return paginated selected-branch orders,
- return paginated selected-branch payments or payment history rows.

The view should remain thin:

- read query parameters,
- call the service/helper,
- render the template.

The template should only render prepared context.

## Query Parameters

Supported parameters:

- `branch`: selected branch id,
- `tab`: `summary`, `orders`, or `payments`,
- `date_from`: inclusive start date,
- `date_to`: inclusive end date,
- `orders_page`: selected orders page,
- `payments_page`: selected payments page.

When changing branches, reset `orders_page` and `payments_page` to page 1.

When changing tabs, preserve branch and date range.

## Empty And Error States

No branches:

- show `No hay sucursales registradas.`
- keep the link back to corporate detail visible.

Invalid branch id:

- ignore it and fall back to the default branch, unless the id belongs to another corporate. In that case, do not expose the other branch and fall back to the default branch.

No orders:

- show a compact empty state in the `Ordenes` tab.

No payments:

- show a compact empty state in the `Pagos` tab.

No route:

- show `Sin ruta asignada` in the selected-branch summary.

Invalid dates:

- fall back to the current month.

## Responsiveness

Desktop:

- corporate summary cards span the top,
- branch list sits on the left,
- selected branch detail sits on the right.

Tablet:

- keep the master-detail layout if there is enough width,
- otherwise stack branch list above detail.

Mobile:

- stack vertically,
- branch list becomes a compact list of full-width links,
- tables remain in responsive wrappers.

## Testing

Add focused Django tests for behavior and rendered content:

- corporate detail page renders the `Ver sucursales / ventas` link.
- corporate branch workspace rejects or 404s for branch clients.
- page selects the first active branch when no branch query parameter is present.
- branch selection only allows branches owned by the corporate.
- corporate totals include all corporate branches.
- order table includes pending, completed, and cancelled orders.
- sales totals exclude cancelled orders.
- payments totals include completed payments and exclude pending credit placeholders.
- orders and payments tabs preserve branch and date range query parameters.
- pagination works independently for orders and payments.
- empty corporate renders the no-branches state.

Manual visual verification should check the page at desktop and mobile widths.

## Out Of Scope

This design does not:

- add charts,
- add exports,
- change client credit rules,
- change payment settlement behavior,
- change invoice fiscal ownership,
- add JavaScript branch loading,
- merge corporate and branch debt into one ledger.

Those can be added later once the branch workspace proves useful in daily operations.
