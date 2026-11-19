# Branch credit debt transfers

The user approved these rules and implementation after updating `main` on
2026-11-04. Work is performed in the existing checkout as requested.

## Behavior

- Enabling a branch's own credit transfers all its outstanding credit-order
  balances from the corporate account to the branch account. Only the unpaid
  remainder moves; completed orders, sales, invoices and payments retain history.
- Disabling own credit transfers outstanding balances back to corporate.
- Reject the entire switch if the destination's existing debt plus the transfer
  exceeds its credit limit. No configuration or financial changes may survive.
- Accounts have independent limits. For ABC's MXN 5,000 line, XYZ's MXN 4,000
  line and MXN 2,000 outstanding, the result is ABC debt 0 / available 5,000 and
  XYZ debt 2,000 / available 2,000.
- Preserve the original payment terms of existing credit orders, including
  invoice-relative terms when the invoice has not been issued yet. New credit
  orders use the terms in effect when credit is first charged.
- Settlement, cancellation, reports, overdue checks and splitting must follow
  the current debt account and count transferred debt once.
- New switches transfer automatically. Existing branches require an explicit
  management command, with preview as the default and capacity checks on apply.

## Approach

We considered retaining debt on its original account with separate branch
reporting, and transferring the unpaid debt when the credit account changes.
The user selected transfer: the branch's current credit line then reflects all
its outstanding order debt. Historical transactions remain immutable; paired
transfer ledger entries record the source release and destination charge.

Orders record the current credit account and a snapshot of credit terms.
Legacy orders fall back to their original purchase account until first touched.
One orchestration service performs validated, atomic transfers; clients' edit
flows and admin call it rather than implementing financial logic themselves.
Unreconciled or ambiguous debt is rejected for manual review, never guessed.

## Constraints

All new functions are typed. Entity queries belong in managers/querysets;
cross-account operations and transactions belong in services. Tenant schemas
remain isolated. The change does not edit issued invoices or silently migrate
existing branches during schema migration.
