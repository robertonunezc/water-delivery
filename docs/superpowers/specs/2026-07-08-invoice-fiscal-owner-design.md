# Invoice Fiscal Owner Design

## Goal

Support corporate invoice data for branch orders while keeping orders, payments, debt, credit terms, and overdue status owned by the operational client that created the order.

The system must support:

- One invoice for a corporate client's own orders.
- One invoice for one branch's orders, issued with corporate fiscal data.
- One invoice for multiple branches' orders under the same corporate, issued with corporate fiscal data.

## Current Behavior

`Invoice.client` currently carries two meanings:

- The client shown on the invoice.
- The client used to filter invoiceable orders.

Branch billing inheritance already exists in the service layer. A branch resolves invoice requirements through its corporate client, and branch-owned invoice data is intentionally ignored. However, invoice order selection still assumes invoice orders belong to the exact same client as `Invoice.client` in several forms/admin paths.

Credit and overdue behavior is order-led today:

- Credit transactions reference `order.client`.
- Payments are attached to orders.
- An invoice is treated as paid when all linked orders are paid.
- For `invoice_due` credit terms, an unpaid order waits until a linked invoice has `emmited_at`, then its due date is `invoice.emmited_at + order.client.credit_config.max_payment_days`.

## Chosen Approach

Use `Invoice.client` as the fiscal client the invoice is issued to. Linked orders determine operational clients, debt owners, payments, overdue status, and branch breakdown.

Core invariant:

```text
An invoice is issued to one fiscal client. It may link many orders, as long as every linked order resolves to that same fiscal client. Payment, debt, overdue, and credit terms remain on each order's client.
```

For client fiscal owner resolution:

- Corporate client: fiscal owner is the corporate client itself.
- Branch client: fiscal owner is the branch's `corporate`.
- Branch without a corporate cannot be invoiced.

## Alternatives Considered

### Add `Invoice.service_client`

Add an optional second client field for branch-specific invoices.

This makes branch filtering simple, but breaks down for one invoice across multiple branches. It also duplicates information already available through linked orders.

### Keep Invoice Attached To Branch And Add `fiscal_client`

Keep `Invoice.client` as the operational client and add a separate fiscal owner field.

This is less disruptive to current order filters, but makes corporate-wide invoices awkward and keeps the primary invoice identity pointed at the wrong business concept. The fiscal identity should be the invoice's main client.

## Data Flow

Invoice creation from selected orders:

1. Receive selected completed, unbilled orders.
2. Resolve the fiscal owner for each order's client.
3. Require all selected orders to resolve to the same fiscal owner.
4. Validate invoice requirements on the fiscal owner: RFC, razon social, and active fiscal address.
5. Create `Invoice.client` with the resolved fiscal owner.
6. Link selected orders through `InvoiceOrderLink`.
7. If `auto_amount=True`, set invoice amount from linked order totals.

Manual invoice editing:

1. `Invoice.client` remains the fiscal owner and should be shown as "Cliente fiscal" or "Emitida a".
2. Order selectors may support an exact-client scope for one branch and a fiscal-owner scope for corporate-wide invoice linking.
3. Every added order is validated against the invoice fiscal owner before it is linked.

## Validation Rules

An order can be linked to an invoice only when:

- The order is completed.
- The order is not already linked to another invoice, except when keeping the current order selectable while editing an existing link.
- The order client's fiscal owner equals `invoice.client`.
- The order's fiscal owner has required invoice data and an active fiscal address.

Selected orders cannot be invoiced together when their resolved fiscal owners differ.

Manual invoices keep the existing amount cap rule: the sum of linked order totals cannot exceed invoice amount. Auto-amount invoices derive amount from linked orders.

## Overdue And Payment Rules

Invoices are not paid directly in the system. Orders are paid. An invoice is paid only when all linked orders are paid.

Debt and overdue behavior remains unchanged in ownership:

- Branch order debt stays on the branch.
- Corporate order debt stays on the corporate client.
- Corporate-level debt is an aggregate view of the corporate client's own debt plus branch debts.
- `invoice_due` due dates are still calculated per order using `order.client.credit_config`, even when the order is linked to a corporate-issued invoice.

If a single corporate invoice links orders from branches with different credit terms, each order keeps its own due date and overdue state.

## UI Impact

Invoice list and edit screens should label `Invoice.client` as the fiscal client to reduce ambiguity.

Invoice detail/edit views should show linked order client names because branch identity now comes from linked orders. A corporate-issued invoice may contain:

- only corporate orders,
- only one branch's orders,
- multiple branches' orders.

Order bulk invoice creation should allow selected orders from different branches under the same corporate. It should reject selected orders from different fiscal owners.

## Service Shape

Add or centralize helpers in `invoice.services`:

```text
get_invoice_fiscal_owner(client)
  if client.type == "branch": require client.corporate and return client.corporate
  return client

validate_order_can_link_to_invoice(invoice, order)
  require completed order
  require unbilled order unless editing current link
  require get_invoice_fiscal_owner(order.client) == invoice.client
  enforce manual invoice amount cap when needed
```

Update `create_invoice_from_orders()` so the selected orders are the source of truth for the fiscal owner. The caller may pass a client for backward compatibility, but the created invoice must use the resolved fiscal owner.

Update invoiceable order queries to support:

- exact-client scope for a specific branch or corporate client's own orders.
- fiscal-owner scope for all unbilled completed orders whose client resolves to the invoice fiscal owner.

## Testing

Add or update tests for:

- Branch-only invoice is issued to the corporate client.
- Multi-branch invoice under one corporate is issued to that corporate.
- Orders from different corporates are rejected.
- Branch without a corporate cannot be invoiced.
- Manual invoice order linking accepts branch orders under the invoice fiscal owner.
- Manual invoice order linking rejects orders whose fiscal owner differs from the invoice client.
- `invoice_due` overdue calculation still uses `order.client.credit_config`.
- Invoice paid status remains derived from linked order payment state.
- Admin/dashboard bulk invoice creation allows same-corporate branch selections and rejects different-corporate selections.
