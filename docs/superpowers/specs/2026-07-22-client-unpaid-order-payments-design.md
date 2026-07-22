# Client Unpaid Order Payments Design

## Goal

Allow staff to select one or more unpaid orders from the client detail page and pay them through a dedicated review screen, without editing the order payment method and losing the audit trail that an order was originally credit.

## Current Behavior

The client detail page renders both the `¡Atención! Pagos Vencidos` table and the `Ventas Recientes` table. Overdue rows currently send `Pagar` to the order flow instead of a payment settlement flow. Recent sales do not provide an order action menu that clearly separates editing from payment.

The app already preserves credit history through:

- `Order.type == "credito"` for the original order type,
- `Payment(method="pending_credit", status="pending")` for the unpaid credit marker,
- `CreditTransaction(transaction_type="purchase")` for the credit debt creation,
- `CreditTransaction(transaction_type="payment")` for debt reduction when credit is paid.

Completed `pending_credit` payments are excluded from `Order.total_paid`, so they act as credit markers rather than money received. A credit order that is later paid can still be identified as a credit order by its order type and credit transaction history.

## Chosen Approach

Create a client-level unpaid-order payment flow.

The client detail page will let staff select unpaid orders directly in the tables they already use, then open a dedicated payment page for review and confirmation. The payment page will handle both single-order and multi-order payments for any unpaid order belonging to that client, not only credit orders.

This keeps order editing separate from payment settlement and gives the user a clear confirmation step before financial records are created.

## UI Changes

On `clients:detail`, add checkboxes to unpaid rows in:

- `¡Atención! Pagos Vencidos`,
- `Ventas Recientes`.

Paid orders should not be selectable. Cancelled orders should not be selectable.

Add a single client-detail selection form that both sections can submit. Each unpaid-order checkbox uses `name="orders"` and the order id as its value. Add a `Pagar seleccionados` action near the relevant table controls. The action opens the new payment page with repeated query parameters such as `?orders=1241&orders=1242`. If the same order appears in both sections, the receiving page will deduplicate it.

For each unpaid row, keep or add a direct `Pagar` action that opens the same new page with that single order preselected.

In `Ventas Recientes`, add an actions menu with:

- `Editar`, pointing to the existing order edit flow used by `orders:get_order`,
- `Pagar`, visible only when `not order.is_paid`, pointing to the new client-level payment page for that order.

## Payment Page

Add a new client-scoped route such as:

```text
/clients/<client_id>/orders/pay/?orders=1241&orders=1242
```

The page displays:

- client name and current balance,
- selected orders,
- each order total, amount already paid, and remaining amount,
- selected unpaid total,
- editable amount field prepopulated with the selected unpaid total,
- payment method selector using settlement methods only.

The page must not allow `pending_credit` as a settlement method.

## Payment Rules

The selected orders can include any unpaid orders for the client.

On submit:

1. Validate every selected order belongs to the URL client.
2. Reject cancelled orders.
3. Reject orders that are already paid.
4. Calculate each selected order's remaining amount as `order.total_amount - order.total_paid`.
5. Sum the remaining amounts.
6. Block the submit if the entered amount is less than the selected unpaid total.
7. Pay each selected order for its full remaining amount.
8. If the entered amount is greater than the selected unpaid total, add the difference to the client's balance.

Partial allocation is out of scope for this version. Underpayment is blocked.

## Credit Settlement

When a selected order has a pending credit marker, settlement must reuse the credit-aware service path so debt is reduced and credit history is preserved:

- create the real `Payment` with the selected settlement method,
- create the related `CreditTransaction(transaction_type="payment")`,
- mark the `pending_credit` marker completed,
- leave `Order.type == "credito"` unchanged.

When a selected order is unpaid but does not have pending credit, the flow should create a normal completed `Payment` for the order's remaining amount.

## Overpayment

If the user enters more than the selected unpaid total, only the selected unpaid total is applied to orders. The excess is added to the client's balance through the existing balance service.

The overpayment `BalanceTransaction` should reference the last selected order because the current model supports one `reference_order`. Its notes should list all selected order IDs and clearly state that the amount is excess from a multi-order payment.

## Error Handling

Show a clear error and do not create partial records when:

- no orders are selected,
- an order does not belong to the client,
- an order is cancelled,
- an order is already paid,
- the amount is less than the selected unpaid total,
- a balance payment is selected but the client has insufficient balance,
- a credit settlement has inconsistent existing payment data and requires manual review.

Financial writes should be wrapped in `transaction.atomic()` so multi-order payment either fully succeeds or fully fails.

## Testing

Add focused tests for:

- client detail renders unpaid-order checkboxes in overdue and recent sales sections,
- paid orders are not selectable for payment,
- `Ventas Recientes` shows `Editar` and conditional `Pagar` actions,
- selected unpaid orders open the new client-level payment page,
- GET payment page prepopulates amount with summed remaining amount,
- POST blocks amount below selected unpaid total,
- POST pays multiple unpaid orders for the same client,
- POST rejects orders from another client,
- POST settles pending credit orders and preserves credit audit history,
- POST adds overpayment to client balance,
- payment writes are atomic when one selected order fails.

Run the narrow client/order/payment tests first, then the broader related test modules if the change touches shared services.

## Out Of Scope

- Partial payment allocation across selected orders.
- Cross-client payment batches.
- Changing invoice payment behavior.
- Changing `Order.type` after payment.
- Replacing the existing single-order `/orders/<id>/pay/` endpoint.
