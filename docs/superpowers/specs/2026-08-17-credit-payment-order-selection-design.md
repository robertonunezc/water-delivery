# Credit Payment Order Selection Design

## Goal

Change client credit management so debt payments are applied to selected credit orders instead of reducing a client's debt as a global manual amount.

The `Gestionar credito` action from `/administrador/clientes` should let staff choose the pending credit orders being paid, show the selected total, and prevent a payment that does not cover the selected orders. Overpayment should continue to become client balance.

## Current Behavior

`clients:pay_credit` uses `ManualCreditTransactionForm` and calls `balance_service.pay_debt()` for `payment`, `forgiveness`, `adjustment`, and `correction`. That reduces `current_debt` directly and may create credit transactions with no related order or payment.

The app already has order-aware settlement in `payment.services.pay_client_orders()`:

- validates selected unpaid orders,
- creates real `Payment` records,
- settles pending credit markers through `settle_credit_order_payment()`,
- creates `CreditTransaction(transaction_type="payment")` linked to the order and payment,
- completes the `Payment(method="pending_credit")` marker,
- adds overpayment to client balance.

## Chosen Approach

Update `pay_credit` to use an order-selection credit payment flow for `Pago de deuda` and `Pago con Saldo`, while keeping non-payment credit actions manual.

This reuses the existing payment service for actual settlement and avoids duplicating accounting logic. The credit management page becomes the place where staff selects pending credit orders for the client context they entered from the admin list.

## Transaction Types

The credit management form should expose:

- `Pago de deuda`
- `Pago con Saldo`
- `Ajuste manual de deuda`
- `Corrección`
- `Cambio de límite de crédito`

Remove `Condonación de deuda` from the form because it overlaps with `Ajuste manual de deuda`.

`Pago de deuda` and `Pago con Saldo` require selected credit orders. `Ajuste manual de deuda`, `Corrección`, and `Cambio de límite de crédito` remain manual actions and do not require order selection.

## Credit Orders List

The page should list open credit orders ordered by newest first.

For a branch client, list pending credit orders owned by that branch.

For a corporate client, list pending credit orders owned by all its branches. The list should include branch context so staff can see which branch each order belongs to.

An order is selectable when it has a credit purchase history and remains unpaid. In practice, use the same source of truth already used by credit reports and pending payment services:

- `CreditTransaction(transaction_type="purchase", reference_order__isnull=False)` identifies credit orders.
- The credit transaction belongs to the effective credit account.
- `Order.objects.active().unpaid()` filters out paid and cancelled orders.

For a corporate client, the selectable orders include all branch credit orders, including branches with their own credit override. Settlement must reduce the effective credit account for each order, so inherited-credit branch orders reduce corporate debt and override branch orders reduce that branch's own debt.

## Payment Rules

On submit for `Pago de deuda`:

1. Require at least one selected credit order.
2. Validate every selected order belongs to the current credit-management scope.
3. Calculate each selected order's remaining amount.
4. Sum the selected remaining amounts.
5. Block the submit when the entered amount is less than the selected total.
6. Settle every selected order for its full remaining amount.
7. Add any excess to the client balance through the existing balance service.

The user-facing underpayment message should explain that the amount does not cover the selected orders and that staff can divide an order before continuing.

On submit for `Pago con Saldo`:

1. Require at least one selected credit order.
2. Use the selected total as the amount to apply.
3. Require the paying client to have enough balance to cover the selected total.
4. Settle every selected order using the `balance` payment method.
5. Do not add overpayment because no extra money is received in this flow.

The paying client is the client from the current `Gestionar credito` screen. For a corporate screen, `Pago con Saldo` uses the corporate balance even when selected orders belong to branches. For a branch screen, it uses that branch's balance.

Partial allocation across orders is out of scope. If the payment amount does not match the selected order set, staff must split orders or take other actions outside this screen before returning.

## UI Behavior

The credit management page should show:

- client name and type,
- balance, debt, credit limit, and available credit for the relevant credit account,
- transaction type selector without `Condonación de deuda`,
- amount field for `Pago de deuda`,
- order selection table for `Pago de deuda` and `Pago con Saldo`,
- selected orders total,
- `Monto agregado - total pedidos seleccionados` indicator for `Pago de deuda`,
- clear disabled or error state when the selected total exceeds the entered amount.

The table should include order id, branch/client name, order date, total, paid amount, and remaining amount. The order id should link to the existing order detail/edit route.

For `Ajuste manual de deuda`, `Corrección`, and `Cambio de límite de crédito`, the page should hide the orders table and behave like the existing manual flow.

## Data Flow

Add a small helper in the client/payment service layer to fetch open credit orders for the credit-management scope. It should return a queryset or list that callers can use for rendering and validation.

`pay_credit` should:

1. Load the client and the pending credit orders for that scope.
2. Render those orders on GET.
3. On POST, branch by transaction type.
4. For `payment`, call `payment_services.pay_client_orders()` with the selected orders, entered amount, and settlement method.
5. For `payment_from_balance`, call an order-payment path that supports a payer client, with payment method `balance` and amount equal to selected total.
6. For remaining manual actions, use the existing balance service functions.

`payment_services.pay_client_orders()` currently validates direct order ownership by client and balance payments spend `Payment.client.balance`. It will need a scoped variant or optional parameters for the payment scope and payer client so corporate clients can pay branch orders without failing ownership validation, and so corporate `Pago con Saldo` spends corporate balance.

## Error Handling

Show a form error and make no financial writes when:

- no order is selected for `Pago de deuda` or `Pago con Saldo`,
- an order is outside the current scope,
- an order is already paid,
- an order is cancelled,
- the amount entered is less than the selected total,
- `Pago con Saldo` is selected and balance is insufficient,
- a credit order has inconsistent existing payment data that requires manual review.

Multi-order writes must stay atomic.

## Testing

Add focused tests for:

- `ManualCreditTransactionForm` no longer exposes `forgiveness`.
- `pay_credit` lists branch pending credit orders newest first.
- `pay_credit` lists all pending branch credit orders for a corporate client newest first.
- `pay_credit` excludes paid, cancelled, and out-of-scope credit orders.
- `Pago de deuda` requires selected orders.
- `Pago de deuda` blocks amount lower than selected total with the split-order guidance.
- `Pago de deuda` settles selected credit orders and links the resulting credit transactions to orders and payments.
- `Pago de deuda` adds overpayment to balance.
- `Pago con Saldo` requires enough balance and settles selected credit orders using balance.
- Corporate `Pago de deuda` can settle branch orders charged to the corporate credit account.

Run the focused clients, payment, and order tests first. Run broader related tests after the focused suite passes if the local database services are available.

## Out Of Scope

- Partial payment allocation.
- Splitting orders inside this screen.
- Invoice payment behavior.
- Migrating historical manual debt payments.
- Removing manual adjustment or correction.
