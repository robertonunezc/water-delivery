# Client Detail Invoices Design

## Goal

Show invoice information on a client detail page when that client requires billing, and make overdue credit rows link to their related invoice when the overdue order is invoiced.

## Current Behavior

The client detail page already shows:

- client billing data and billing frequency,
- recent orders,
- recent payments,
- overdue credit orders through `clients.services.pending_payment_service.get_overdue_orders_for_client()`.

Orders are linked to invoices through `InvoiceOrderLink`. The existing fiscal-owner design treats `Invoice.client` as the fiscal client that receives the invoice. Linked orders remain the source of truth for operational client ownership, payments, debt, and overdue status.

Because of that, filtering invoices only by `Invoice.client == viewed_client` would hide branch invoices issued to a corporate fiscal owner.

## Chosen Approach

Use order-linked invoices for the client detail page.

The invoice list on `clients:detail` will include distinct invoices that have at least one linked order whose `order.client` is the viewed client. This means:

- a corporate client sees invoices linked to the corporate client's own orders,
- a branch client sees invoices linked to that branch's orders, even if `Invoice.client` is the corporate fiscal owner,
- a multi-branch corporate invoice can appear on each relevant branch page if it contains orders from that branch.

The invoice section only renders when `client.requires_billing` is true. The user asked for invoices only for clients that require invoices, and keeping the render condition there avoids adding billing noise to ordinary delivery clients.

## UI Changes

Add a compact "Facturas" section in the main client detail content area. It should list:

- invoice id,
- fiscal client,
- serie,
- folio,
- emitted date,
- amount,
- paid amount,
- pending amount,
- action link to the existing `admin_edit_invoice` custom view.

If the client requires billing but has no linked invoices, show a muted empty state in the invoice section.

Add a new "Factura" column to the `¡Atención! Pagos Vencidos` table. For each overdue order:

- show a link to the related invoice when the order has an `invoice_links` entry,
- show a muted dash when the order is not linked to an invoice.

## Data Flow

Client detail view:

1. Load the viewed client.
2. Build the current order, payment, route, billing, and overdue context as before.
3. When `client.requires_billing` is true, query `Invoice` through linked orders:

   ```text
   Invoice.objects.filter(invoice_links__order__client=client).distinct()
   ```

4. Select and prefetch related data needed by the template:

   - `client` for fiscal client name,
   - `invoice_links__order__payments` for paid and pending calculations.

5. Add the queryset to context as `client_invoices`.

Overdue payment data already prefetches `invoice_links__invoice`, so the template can use each overdue order's prefetched invoice links without a new per-row query.

## Error Handling

No new error states are needed.

If an overdue order somehow has multiple invoice links, render the links that exist. The current business rules intend one invoice per order, but the template should not fail if old data violates that assumption.

If an invoice has no emitted date or file, the table should render a dash or existing data fields rather than hiding the row.

## Testing

Add focused client detail tests for:

- a client with `requires_billing=True` sees a linked invoice in the client detail invoice section,
- a client with `requires_billing=False` does not render the invoice section even when an invoice link exists,
- a branch with `requires_billing=True` sees a corporate-issued invoice linked to one of its orders,
- the overdue payments table renders the invoice link for an invoiced overdue order,
- the overdue payments table renders a muted dash for an overdue order without an invoice link.

The implementation should use existing Django test patterns in `clients/tests.py` and run the narrow client tests first, then the relevant client test module.
