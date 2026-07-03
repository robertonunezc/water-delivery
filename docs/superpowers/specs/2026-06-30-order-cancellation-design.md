# Order Cancellation Design

## Goal

Allow orders in any status to be cancelled without deleting business records. Cancellation must preserve audit history, reverse internal balance and credit effects, and block cases that need manual review.

## Current Behavior

The normal `Cancelar Pedido` flow only accepts pending orders. It deletes the order and its items, and rejects orders with any payments. Admin/bulk cancellation is separate and only marks orders as `CANCELLED`.

## Chosen Approach

Use status-based cancellation for the normal order cancellation flow.

- Orders are marked `CANCELLED`; they are not deleted.
- Payments are marked `reversed`; they are not deleted.
- External payments such as cash, card, bank transfer, PayPal, and similar methods are marked `reversed` only. The money is assumed to have been returned outside the system.
- Internal balance and credit effects are reversed through ledger transactions.
- The entire cancellation runs inside one `transaction.atomic()` block.
- Already-cancelled orders are idempotent no-ops and do not create duplicate reversal transactions.

## Financial Reversal Rules

Balance payments:

- If an order payment used client balance, cancellation restores that amount to the client's balance.
- The system creates a `BalanceTransaction` reversal entry linked to the order and payment.

Extra balance from `cantidad_cobrada`:

- If an order added extra money to the client's balance, cancellation must remove that added balance.
- If the client no longer has enough balance to remove, cancellation is blocked for manual review.
- The service returns a clear error explaining the required amount and current available balance.

Credit orders:

- If the order created client debt, cancellation reverses that debt with a `CreditTransaction`.
- If the credit order was later settled, cancellation reverses the settlement effect first, then reverses the original purchase debt effect.
- The ledger must show both the original movement and the reversal movement instead of editing historical transactions.

External payments:

- External payment methods are marked `reversed`.
- No client balance or debt mutation is created for those payments in this first version.

## Manual Review Blocks

Cancellation is blocked when:

- The order is linked to an invoice.
- Reversing balance added by the order would require more balance than the client currently has.
- The service detects financial state that does not match expected order-linked payments or transactions.

Blocked cancellation attempts are persisted on the order so they are visible after the request ends. The order remains in its current status and is marked for staff review.

Add cancellation review metadata to `Order`:

- `cancellation_review_required`
- `cancellation_review_reason`
- `cancellation_requested_at`
- `cancellation_requested_by`

When a non-staff user hits a manual-review block, the service sets the review metadata and returns a message explaining that the order was marked for review. Staff users can see the same review state and are responsible for resolving the underlying issue before retrying cancellation.

Staff review does not bypass accounting rules in the first version. Staff approval means:

1. Inspect the order and review reason.
2. Fix the financial state manually using existing admin/accounting tools.
3. Retry cancellation.

If the financial state is valid after review, cancellation succeeds. If not, the order remains marked for review.

## QuerySet API

Add explicit query helpers on `OrderQuerySet`:

- `active()` returns non-cancelled orders.
- `cancelled()` returns only cancelled orders.
- `including_cancelled()` returns all non-deleted orders.

Keep `Order.objects` including cancelled orders for now, so admin/detail lookups remain predictable. Update sales, invoice eligibility, reports, route work, and other business queries to call `active()` where cancelled orders should not count as live sales.

## UI Behavior

Update the normal cancellation UI copy:

- Stop saying the order and products will be deleted.
- Explain that the order will be marked cancelled and internal balance or credit effects will be reversed when possible.
- Show manual-review block errors returned by the service.

Update the orders list to make blocked cancellations easy to find:

- Show a visible `Requiere revisión de cancelación` badge on orders with `cancellation_review_required=True`.
- Add a `Revisión requerida` filter.
- For staff users, show a `Reintentar cancelación` action.
- For non-staff users, show an `En revisión` state so they know their cancellation request was recorded.
- Add a staff-facing count for orders requiring cancellation review in the orders list header.

## Service Shape

Replace the pending-only cancellation service with a broader order cancellation service:

```text
cancel_order(order, user, reason=None)
  lock order
  lock client
  lock payments
  if order is already CANCELLED: return success/no-op
  if order is invoiced: mark review required and reject
  calculate internal balance/credit reversals
  if added balance cannot be removed: mark review required and reject
  if financial state is unexpected: mark review required and reject
  create balance reversal transactions
  create credit reversal transactions
  mark payments reversed
  mark order CANCELLED
  clear cancellation review metadata
```

The service owns orchestration, locking, idempotency, and transactions. Views and admin actions should call this service instead of implementing cancellation rules inline.

## Testing

Add tests for:

- Pending orders are cancelled by status and not deleted.
- Completed orders with external payments are cancelled and payments become `reversed`.
- Balance payments restore client balance.
- Extra balance from `cantidad_cobrada` is removed when available.
- Cancellation is blocked when added balance was already spent.
- Credit purchase debt is reversed.
- Settled credit orders reverse settlement then purchase effects.
- Invoiced orders are blocked.
- Blocked cancellations persist cancellation review metadata.
- Staff can see orders requiring cancellation review in the orders list.
- Successful retry after staff fixes financial state clears cancellation review metadata.
- Already-cancelled orders are idempotent.
- `active()`, `cancelled()`, and `including_cancelled()` return expected orders.
