# Credit Inheritance Balance Design

## Problem

Branch credit orders currently validate and mutate credit on the branch client even when the branch does not own its credit configuration. In the reported case, Corporate A has a credit limit of $1000 and Branch B places a $500 credit order. The system creates the branch order, but Corporate A's available credit is not reduced from $1000 to $500.

## Goals

- Branches with `credit_override_enabled=False` must inherit corporate credit availability, emergency stop, and debt ledger.
- Branches with `credit_override_enabled=True` must use their own credit availability, emergency stop, and debt ledger.
- Corporate clients must continue using their own credit configuration.
- The operational order and pending-credit payment must remain associated with the branch that placed the order.
- Credit transactions for inherited branch credit must be recorded on the corporate client so corporate debt and available credit are correct.
- Settlement and reconciliation of inherited branch credit orders must reduce the same credit account that was charged.

## Non-Goals

- No schema changes.
- No migration of historical branch credit transactions.
- No change to cash, bank transfer, card, PayPal, or balance-only payments.
- No UI redesign.

## Approach

Add a single model-level resolver on `Client` for the effective credit account:

```python
def get_credit_account(self) -> "Client":
    if self.type == "branch" and self.corporate_id and not self.credit_override_enabled:
        return self.corporate
    return self
```

Then update credit-specific services to resolve the account before validating credit, creating purchase transactions, settling pending credit, reconciling unapplied payments, and reporting current debt/available credit from payment helpers.

Order and payment ownership stays unchanged: `Order.client` and `Payment.client` continue to point to the ordering branch. Only `CreditTransaction.client` and `Client.current_debt` mutations use the effective credit account.

## Data Flow

For a branch without override:

1. Checkout receives a credit order for Branch B.
2. Balance usage still uses Branch B's prepaid balance.
3. Remaining credit amount validates against Corporate A's `can_pay_with_credit`, `credit_limit`, and `current_debt`.
4. The `pending_credit` payment is created for Branch B and the order.
5. The credit purchase transaction is created for Corporate A with the branch order and pending payment references.
6. Corporate A's `current_debt` increases, so available credit decreases.
7. When the pending credit is paid, the settlement reduces Corporate A's debt.

For a branch with override, steps 3, 5, 6, and 7 use Branch B instead.

## Error Handling

- If the effective credit account has `can_pay_with_credit=False`, return the existing `Cliente no puede pagar con credito` error.
- If the effective credit account lacks enough available credit, return the existing credit-limit error with the effective account's available amount.
- If settlement cannot reduce the full amount from the effective credit account, raise the existing settlement error.

## Test Plan

- Add a payment service regression test showing a non-override branch order charges corporate debt and leaves branch debt unchanged.
- Add a payment service regression test showing a non-override branch order is blocked by corporate credit limit.
- Add a payment service regression test showing an override branch order uses branch debt and leaves corporate debt unchanged.
- Add a settlement regression test showing a non-override branch pending-credit payment reduces corporate debt.
- Add an order service regression test showing `process_order_payment(..., payment_method="credit")` uses the corporate credit account for a non-override branch.
- Run the focused payment/order credit test slice. Run the broader app tests after the focused slice passes when the local database services are available.
