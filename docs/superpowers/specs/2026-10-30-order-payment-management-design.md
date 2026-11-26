# Order payment management and append-only reversals

Status: approved product definition (updated 2026-11-20 with `CancelacionDePagos - Matriz(Hoja1).csv` scenarios and post-Oct-30 `main` alignment).

## Intent

Give managers and administrators clear, auditable ways to inspect and reverse (cancel) a single payment or standalone balance deposit:

- A `Pagos` action on an order row opens that order's payment history.
- A standalone `Administración → Pagos` page lists order payments and standalone balance deposits (`abonos a saldo`) across clients/orders.

The only new financial action is reversal of **one whole payment** (or **one whole standalone balance deposit**) at a time — **no bulk cancellation**. Before confirmation, staff must see every balance, debt, and order-payment effect. Reversal preserves the original payment/deposit and creates a new linked compensating transaction. All financial totals must account for both transactions.

This is a project spanning payment recording, financial queries, credit collection, reports, and order cancellation. Adding only a page or changing the original payment status would not satisfy the agreed behavior.

## Decisions confirmed in the interview

1. Use one action named `Revertir pago`; cancellation and reversal are synonyms in this payment UI. It records accounting changes. Returning physical money or calling a payment provider is outside scope.
2. Reverse one whole payment at a time. No partial reversals, bulk reversals, payment editing, or new payment-registration UI.
3. Only managers/admins can access the management pages or confirm reversals. Require a reason; retain actor and timestamp.
4. Never change the original payment's status, amount, method, account, or date as part of reversal. Create a new reversal transaction linked to it.
5. **Order payment reversal converts unpaid amount into client credit debt (`Orden queda registrada a crédito`)**:
   - Reversing a prior credit-settlement payment restores the debt originally reduced by that payment on its originally recorded credit account (accounting for any branch credit transfers on `Order.credit_account` / `CreditTransaction`).
   - Reversing an original non-credit payment made at order time (cash, card, transfer, balance, etc.) converts that newly unpaid order amount into client credit debt (`current_debt` + `CreditTransaction`), so the order appears in `Pagar Créditos` and credit reports.
   - Changes in credit ownership, enabled status, or limit must not prevent recording/restoring that debt.
6. **Mixed payments (`Saldo + Otro método` or `Saldo + Crédito`)**:
   - Reversing one payment leaves any other effective payment intact (so the order becomes partially paid if another method remains paid), and converts only the reversed payment's amount into credit debt.
7. **Two-step balance handling (newest → oldest)**:
   - Reversing an order's `Saldo` payment restores the balance consumed by that payment to the actual recorded balance payer (which can differ from the order client) and converts the unpaid order portion into credit debt.
   - Reversing a standalone `abono a saldo` (`BalanceTransaction` deposit not linked to an order) deducts the deposit amount from the client's available balance.
   - If a balance deposit or excess-balance deposit was already spent on newer payments, cancelling it is blocked with the exact balance shortage — the user must cancel newer balance payments first (newest → oldest) to dismantle the chain.
8. Remove excess balance originally created by the same collection (`Pago > Total de la orden`, both at order creation and in `Pagar Créditos`). For a collection covering several orders or payment methods, remove the whole excess once, on the first payment reversal in that collection. Other payments remain effective.
9. If the combined reversal would leave any affected balance account negative, block it and display the shortage. Balance restored by this same operation counts toward covering the removal on that same account.
10. Allow reversal of payments on invoiced orders. Payment reversal does not cancel the order or invoice.
11. When historical records cannot establish the exact financial effects, block reversal with a clear review-required explanation.
12. Preview all effects before confirmation, including money removed from balance, balance restored, resulting debt, and the order's resulting amount due.
13. **No bulk cancellation**: Only single-payment (or single-deposit) cancellation is allowed. Remove Django admin's bulk `reverse_selected_payments` action and reject bulk order cancellation when any selected order requires real-payment reversal.

## Product scenario matrix (`CancelacionDePagos - Matriz`)

| Scenario | Chronology | Amount | Method | Expected result |
| --- | --- | --- | --- | --- |
| Order payment | At order creation | `Pago = Total` | Any except `Saldo` | Order becomes unpaid & registered as credit debt (`current_debt` + `CreditTransaction`). |
| Order payment | At order creation | `Pago > Total` | Any except `Saldo` | Order becomes unpaid & registered as credit debt; excess (`pago - orden`) removed from client balance (blocked if already spent; dismantle newest → oldest). |
| Order payment | Prior `abono a saldo` used at order creation | `Saldo` covers order(s) | `Saldo` | Step 1: reversing order `Saldo` payment restores balance & marks order as credit debt. Step 2: user may then reverse the earlier `abono a saldo` to deduct it from balance. |
| Order payment | Prior `abono a saldo` used at order creation | `Pago < Total` | `Saldo + Crédito` | Reversing `Saldo` payment restores balance & adds that portion to credit debt (order fully on credit). Step 2: optional reversal of earlier `abono a saldo`. |
| Order payment | Prior `abono a saldo` used at order creation | `Pago < Total` | `Saldo + Otro método` | Reversing `Saldo` payment restores balance, leaves order partially paid (other method intact), and registers reversed portion as credit debt. Step 2: optional reversal of earlier `abono a saldo`. |
| Order payment | Post-order `[Pagar Créditos]` | `Pago = Total` | `Saldo` | Order returns to credit debt; `Saldo` restored to available balance. |
| Order payment | Post-order `[Pagar Créditos]` | `Pago = Total` | Any except `Saldo` | Related order(s) return to credit debt. |
| Order payment | Post-order `[Pagar Créditos]` | `Pago > Total` | Any except `Saldo` | Related order(s) return to credit debt; excess balance created by that collection is removed (once, on first member reversal). |
| Standalone balance deposit | `Abono a saldo` (no order) | Any positive | N/A (deposit) | Deposit amount deducted from client available balance via append-only compensating `BalanceTransaction` (blocked if already spent; dismantle newest → oldest). |

## Approaches

### Recommended: payment and reversal entries in the existing transaction history

Extend `Payment` with an explicit entry kind and a unique link from a reversal to its original payment. Store positive magnitudes and use a shared signed monetary contribution for calculations. A collection identity connects all receipts from one collection and its excess-balance deposit.

This keeps one chronological payment history and lets order, invoice, client, and reporting queries use the same net calculation. It requires updating consumers that currently equate `status='completed'` with money received and ensuring reversal creation never invokes receipt-side accounting hooks.

### Alternative: separate reversal model

A dedicated reversal model can preserve original payments and isolate reversal creation from `Payment.save()`. However, histories and date-based financial aggregates would have to merge two event sources consistently. It offers less benefit here because both the requested UI and the existing reporting code revolve around payment transactions.

The recommended approach is the agent's technical proposal under the user's instruction to continue with the recommendations; approval of this document confirms it. Mutation or deletion of the original payment is explicitly ruled out by the user.

## Transaction model and net amounts

- Add a kind such as `payment` or `reversal`; existing rows default to `payment`.
- Add a nullable, unique `reversal_of` relation. It must be populated only for reversal entries.
- A reversal copies the original's order, payer, payment method, and full amount. Its own actor, timestamp, and required reason identify the new operation.
- The new reversal transaction is a completed accounting event with type `Reversión`; do not represent success by changing the original to the legacy `reversed` or `failed` status.
- A completed ordinary real payment contributes `+amount`.
- Its completed reversal contributes `-amount`.
- Credit markers (`pending_credit`), pending payments, failed payments, and legacy rows already stored as `status='reversed'` contribute zero.
- A full reversal can exist only once. A reversal cannot itself be reversed in this version.
- Historical `failed`/`reversed` rows remain as recorded. Do not manufacture another negative event for them or repeat their previous side effects.
- Keep money values as `Decimal` with the existing currency precision.

Put signed expressions and receipt/reversal selection in `PaymentQuerySet`/manager. Provide separate meanings for all chronological financial events, effective receipts, and receipts eligible for reversal; do not overload `not_reversed()` for all three.

Original receipts and their reversal entries remain visible. The original can have a derived `Con reversión` badge and link to the new entry without altering its stored status. The reversal row shows its signed amount and the original payment reference.

Posted reversal entries and their originals must not be editable or deletable through the management UI or Django admin. Remove the existing admin path that directly changes payment status. Keep schema-level uniqueness and service validation in addition to UI controls.

## Collection and financial-effect attribution

Persist a collection identity for new receipt-writing paths, including single-order, mixed-method, selected-order, and credit-settlement flows. A collection records its actual receipt members and explicit references to any excess-balance deposit and its owner. Credit markers are not received-money members.

Reversal must identify the original balance deductions and credit reductions using explicit ledger references. Add structured references from compensating entries to the entries they compensate and to the new reversal transaction. Preserve original ledger entries. Enforce that an excess-balance deposit is compensated at most once, even if different members of its collection are reversed concurrently.

The first confirmed reversal from a collection removes its entire outstanding excess. Later member reversals show that the excess has already been removed and do not remove it again. Lock the collection as well as the selected payment when deciding this.

Do not reconstruct historical collection membership or financial effects from matching amounts, timestamp proximity, free-text notes, or current order type. A missing collection identity is not proof that a historical receipt created no shared excess. Permit a historical reversal only when structured evidence establishes all its effects; otherwise show the specific missing/ambiguous attribution and require review. The extent of historical eligibility depends on the data, and broad historical repair is outside this project.

## Reversal effects

Build a deterministic reversal plan from the selected original payment and its recorded financial effects:

1. A new payment reversal subtracts the original received amount from net order payments.
2. New balance ledger entries restore the amount actually consumed from each recorded balance payer.
3. New credit ledger entries record/restore credit debt for the reversed payment amount:
   - For a prior credit-settlement receipt: restore the recorded debt reduction on the originally recorded credit account (accounting for branch credit transfers).
   - For an original non-credit receipt made at order creation: record credit debt (`CreditTransaction`) for the reversed amount on the order's `credit_account` (or resolved client credit account) so the order appears in `Pagar Créditos` and credit reports, regardless of current credit enabled status or limit.
4. A new balance ledger entry removes the collection's as-yet-unreversed excess from its original balance owner.
5. For a standalone `abono a saldo` (`BalanceTransaction` with `transaction_type='deposit'` and no order): create an append-only compensating `BalanceTransaction` linked to the original deposit, deducting its full amount from `client.balance` (blocked if `client.balance < deposit.amount`).
6. Calculate each account's combined final balance before checking affordability. Never offset one client's shortage with another client's balance.
7. Recompute the order's net paid and unpaid amounts and affected invoice payment state. The order's delivery status and invoice lifecycle status remain unchanged.

Credit debt restoration/creation during reversal can exceed a changed credit limit or apply to an account currently disabled for new credit purchases.

Example: \$1,000 order, \$400 original cash, \$600 credit, later settled with \$600 cash:

- Reversing the later \$600 creates a `-600` payment event and restores \$600 recorded credit debt.
- Reversing the original \$400 creates a `-400` payment event and converts the newly unpaid \$400 into credit debt.
- If both are reversed, the order has \$1,000 unpaid, all \$1,000 tracked as outstanding credit debt eligible for `Pagar Créditos`.

## Outstanding credit, branch transfers, and repayment

Derive outstanding credit per `(order, credit_account)` from order-linked `CreditTransaction` ledger deltas — including purchases, payments, payment reversals, purchase reversals, and branch credit transfers (`credit_transfer_out` / `credit_transfer_in` introduced in `c51a1c7`) — using `lock_order_credit_clients` for atomic locking.

- Reversing any order payment increases outstanding credit for that order by the reversed payment amount so the order is immediately eligible in `Pagar Créditos` and credit reports.
- General order payment flows and `Gestionar crédito` settle outstanding credit on selected orders and explicitly link their credit-reduction ledger entries so later reversals are unambiguous.
- Reversal does not reopen or rewrite an old credit-marker payment (`pending_credit`). Credit eligibility, reconciliation, selection totals, and overdue amounts use outstanding credit from ledger deltas, not marker status alone.
- Preserve existing due-date anchors (`Order.credit_terms_snapshot` where present, otherwise existing order/invoice anchors). Reversal does not grant a fresh payment term.
- Credit reports (including `credit_report_service.py` and `credit_report_payments.js`) and client/order summaries reflect signed net payments and ledger-derived outstanding credit consistently.

## Pages and navigation

Use the repository's existing server-rendered Spanish administration layout and design system.

### Order payment history

Add a `Pagos` action to order rows in the administration order list and the existing client order tables. Link to a dedicated order-scoped page; preserve a safe return destination.

Show client and order context, order total, net paid, total unpaid, outstanding credit, ordinary unpaid, and complete chronological payment/reversal history. Credit markers can appear as clearly labeled, read-only debt history and do not contribute to received-money totals.

Each transaction shows date, ID, kind, method, signed amount, recorded state, actor, and original/reversal links. Only eligible effective receipts have `Revertir pago`.

### Standalone payments

Add `Pagos` to the administration navigation. Show real receipt and reversal events across orders, newest first, with pagination and filters for order, client/payer, dates, method, kind, and effective reversal state. Exclude credit markers from the main received-money list.

Use unfiltered all-time history by default; filter summaries use the same signed contribution and event-date rules as their rows. Link each order to its order payment history.

### Required reversal preview

Opening `Revertir pago` performs no financial writes. The review screen shows:

- Payment ID, order, original date, payer, method, and full payment amount.
- The new negative payment entry and the original payment that remains intact.
- For every affected account: account name, balance before, restoration/removal components, and balance after.
- For every affected credit account: debt before, debt restored, debt after, and resulting available credit.
- Order net paid/unpaid before and after, including credit versus ordinary unpaid.
- Any linked invoice's resulting payment state; explain that the invoice remains in place.
- Whether excess is removed now or was already removed by a previous collection-member reversal.
- Any blocking issue, exact balance shortage, or review-required inconsistency.
- Required reason, `Confirmar reversión`, and a cancel/back action.

Disabled confirmation and its explanation remain visible when reversal cannot proceed. Confirmation records accounting only and does not initiate an external refund.

## Preview consistency and atomic confirmation

Use one typed service-layer planner for both preview and execution, with entity query logic in managers/querysets. Models enforce entity invariants and do not orchestrate transactions, authentication, or cross-account side effects.

The server issues a signed, expiring preview token identifying the selected payment and the complete planned effects/current relevant state. The browser never supplies authoritative amounts. On POST:

1. Verify authorization, CSRF, required reason, and preview token.
2. Within `transaction.atomic()`, lock the selected payment, its collection, affected order(s), referenced ledger effects, and affected accounts in a consistent order.
3. Rebuild the plan from current database state and compare it with the preview.
4. If anything affecting the result changed, perform no writes and present a refreshed preview requiring confirmation again.
5. Otherwise create the reversal event and all compensating ledger entries, and update affected derived invoice-link flags together.
6. Commit everything or nothing. A duplicate confirmation cannot create duplicate reversal entries, refunds, restored debt, or excess removal.

Use the current operation date/time for new entries; no backdating control in this version. A reversal of last month's payment belongs to this month's financial activity. Historical date-range reports retain the original receipt in its original period and the negative reversal in its own period.

## Authorization

Agent proposal for the agreed manager/admin rule: active authenticated users who are Django staff/admins, or whose linked employee position is `manager`, can use these pages and actions. Mere authentication or permission to collect payments is insufficient. Centralize the permission helper and enforce it on every GET and POST, including direct URLs. Read-only financial history elsewhere retains its existing access rules.

## Integrations required for consistency

- `Order.total_paid`, `OrderQuerySet.with_payment_totals()`, and paid/unpaid/closed predicates.
- Invoice ORM/Python totals, balance, payment status, and stored `InvoiceOrderLink.is_paid` / `partially_paid` flags for affected orders. Synchronize those flags after both reversal and subsequent repayment.
- Client totals and chronological financial history, including balance/credit compensation labels and signs.
- Corporate/branch payment histories and date-filtered totals.
- Sales/payment-method summaries, CSV exports, report method filters/buckets, last effective payment indicators, and receipt PDF payment tables.
- Existing payment creation and credit settlement/reconciliation, excluding reversal events and reversed original receipts from candidates that would apply accounting again.
- Credit selection, overdue calculations, credit reports, and repayment amounts as described above.
- Django admin: replace direct/bulk status mutation with the shared single-payment preview/confirmation flow; do not provide an alternate bypass.
- Order cancellation: create missing reversal events and financial compensations through the same orchestration, then reverse only remaining original purchase debt and cancel the order. Skip already compensated effects, subtract prior excess removals, and retain existing invoice-cancellation guards. Cancellation must not change original real-payment statuses or repeat prior refunds/debt restoration. Its internally generated reason identifies order cancellation.
- Order splitting: never split a reversal event or change an original payment already paired with a reversal. As a bounded proposal, block splitting orders with reversal history in this version and explain why; preserve existing behavior for other orders while carrying collection/effect attribution into any split receipt records. A general immutable split-allocation redesign is outside scope.

Money totals and event counts have different semantics: signed net money includes reversals; receipt counts describe original received-payment events, with a separate reversal count where helpful. Do not make a reversal count as another positive payment. Method filters use the relevant receipt method, not whichever event happens to be first.

## Verification requirements

Service functions must be explicitly typed and unit-tested under repository conventions. Cover:

- Original payment and ledger rows remain unchanged after full reversal; a unique linked negative contribution is created.
- SQL/Python order and invoice totals agree for receipts, reversals, credit markers, and legacy states.
- Credit settlement reversal, balance-funded credit settlement, original cash reversal on mixed orders, and repayment of mixed ordinary/credit outstanding amounts.
- Original corporate credit owner and actual balance payer remain correct after configuration changes; lowered/disabled credit does not prevent debt restoration.
- Excess removal for single and multi-order/method collections, exactly once across member reversals.
- Spent excess blocks without writes; combined same-account balance restoration can make reversal affordable; accounts cannot subsidize each other.
- Preview matches execution; concurrent changes require a refreshed confirmation; duplicate submissions and simultaneous member reversals cannot double compensate.
- Manager/staff access versus unauthorized collectors; required reason; CSRF; GET has no financial writes.
- Invoiced orders remain invoiced and payment state/affected link flags update; subsequent repayment updates them again.
- Credit reports and overdue amounts distinguish credit from ordinary unpaid and preserve existing due-date anchors.
- Historical ambiguous attribution blocks with explanation; old reversed/failed records are not double-subtracted or compensated again.
- Order cancellation after payment reversal and the reverse order of operations do not duplicate any effects; failed cancellation remains atomic.
- Splitting with reversal history is blocked without mutation; permitted splits retain attribution.
- Reversal appears on its own event date in reports and exports; histories and receipt PDFs show correct signs and references.

Run focused payment/client/order/invoice/report tests for the touched behavior, then the relevant broader suites. Exercise the two pages and the required preview in the browser with representative credit, balance, surplus, and blocked cases. Do not use the production database for verification.

## Explicit exclusions

No partial or bulk reversals, reversal of a reversal, provider refunds, new payment entry/edit UI, automatic repair of ambiguous historical collections, historical credit-term snapshotting, or general order-split ledger redesign. This design does not migrate old reversal history into invented new transactions.

## Calls proposed by the agent for approval

- Same-table typed payment/reversal events and explicit collection/effect links.
- One shared preview/execution service for all reversal paths; signed net calculations across affected consumers.
- Existing due-date anchors, current reversal timestamp, all-time default standalone history, and server-rendered UI.
- Manager-role-or-Django-staff authorization, as specified above.
- Preserve legacy history and block ambiguous historical effects without guessed backfills.
- Temporarily block splitting an order with reversal history; retain supported splits otherwise.

Exact route names, model/helper names, token expiry, indexes, template decomposition, and styling details are left to the implementer within these rules.

## Resolved decisions (2026-11-20)

- **No bulk cancellation**: Only single payment (or single standalone `abono a saldo`) cancellation is supported in this version. Django admin's bulk `reverse_selected_payments` action is removed, and bulk order cancellation rejects any selection containing orders with actual received payments (directing those to individual review).
- **Order cancellation permission**: Cancelling an order that requires reversing actual received payments requires manager/admin authorization, while retaining existing collector permissions for cancellations that reverse no actual receipt.
- **Unpaid amount becomes credit debt**: Reversing an original non-credit payment made at order creation converts that unpaid amount into client credit debt (`current_debt` + `CreditTransaction`) so it appears in `Pagar Créditos`.
- **Two-step balance dismantling**: Reversing an order's `Saldo` payment restores balance to the payer and registers the order amount as credit debt; reversing a standalone `abono a saldo` (or excess balance) deducts from balance and blocks if already spent until newer balance payments are reversed first (newest → oldest).
- **Standalone `abono a saldo` included**: Cancelling standalone `BalanceTransaction` deposits (`deposit`, no order) is included in `feat/payments-mgmt` with the same preview + required reason + append-only reversal flow.
