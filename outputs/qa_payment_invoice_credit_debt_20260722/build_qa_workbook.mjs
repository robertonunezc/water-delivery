import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const outputDir = path.resolve(".");
const outputPath = path.join(outputDir, "qa_manual_pagos_facturas_credito_deuda.xlsx");

const statuses = ["Sin iniciar", "Aprobado", "Fallido", "Bloqueado", "N/A"];
const priorities = ["P0", "P1", "P2"];
const areas = [
  "Pagos",
  "Balance",
  "Deuda",
  "Órdenes a crédito",
  "Config crédito",
  "Facturas",
  "Cancelaciones",
  "Reportes",
];

const step = (items) => items.map((item, index) => `${index + 1}. ${item}`).join("\n");
const expect = (items) => items.map((item) => `- ${item}`).join("\n");
const areaLabels = {
  Payments: "Pagos",
  Balance: "Balance",
  Debt: "Deuda",
  "Credit Orders": "Órdenes a crédito",
  "Credit Config": "Config crédito",
  Invoices: "Facturas",
  Cancellations: "Cancelaciones",
  Reports: "Reportes",
};

const manualCases = [
  {
    id: "PAY-001",
    area: "Payments",
    priority: "P0",
    scenario: "Single contado order paid fully with cash",
    preconditions: "Client has a pending contado order with total_amount = 100.00 and no existing payments.",
    steps: step([
      "Open the order payment screen for the order.",
      "Use amount 100.00 and payment method Efectivo/cash.",
      "Submit the payment.",
      "Open the order and client detail payment history.",
    ]),
    expected: expect([
      "Response/UI indicates success.",
      "A completed Payment exists for 100.00 with method cash.",
      "Order remains payable/paid based on total_paid, and no balance or debt movement is created.",
    ]),
    postChecks: "Check Payment admin/list, order total_paid, and client payment history.",
    sourceTests: "payment/tests.py:76, payment/tests.py:118",
    sourceCode: "payment/services.py:285, payment/services.py:68, orders/views.py:113",
  },
  {
    id: "PAY-002",
    area: "Payments",
    priority: "P0",
    scenario: "Split payment uses client balance plus another method",
    preconditions: "Client balance = 30.00. Contado order total_amount = 50.00.",
    steps: step([
      "Open order checkout/create order screen.",
      "Confirm payment breakdown shows 30.00 from saldo and 20.00 remaining.",
      "Choose cash/bank transfer for the remaining payment method.",
      "Complete payment.",
    ]),
    expected: expect([
      "Two payments are created: balance 30.00 and selected method 20.00.",
      "Client balance decreases to 0.00.",
      "BalanceTransaction exists with transaction_type payment for 30.00.",
      "Order is marked COMPLETED.",
    ]),
    postChecks: "Client detail payment history should show the balance deduction and external payment.",
    sourceTests: "payment/tests.py:56, orders/tests.py:1443",
    sourceCode: "payment/services.py:216, payment/services.py:68, orders/static/orders/js/create_order.js:1075",
  },
  {
    id: "PAY-003",
    area: "Payments",
    priority: "P0",
    scenario: "Split payment total mismatch is rejected",
    preconditions: "Contado order total_amount = 100.00.",
    steps: step([
      "Submit a split payment payload or UI selection whose amounts sum to 90.00.",
      "Try to complete the order.",
    ]),
    expected: expect([
      "Payment is rejected with a message that the payment sum must equal the order total.",
      "No new payments are created.",
      "Order status does not move to COMPLETED from this submission.",
    ]),
    postChecks: "Check order payments count before and after.",
    sourceTests: "payment/tests.py:56, payment/tests.py:272",
    sourceCode: "payment/services.py:216",
  },
  {
    id: "PAY-004",
    area: "Payments",
    priority: "P0",
    scenario: "Balance payment with insufficient saldo is rejected",
    preconditions: "Client balance = 30.00. Order total or payment amount = 50.00.",
    steps: step([
      "Attempt to pay 50.00 using Saldo/balance.",
      "Submit the payment.",
    ]),
    expected: expect([
      "Payment is rejected with an insufficient balance message.",
      "No completed balance Payment is created.",
      "Client balance remains 30.00.",
    ]),
    postChecks: "Check client balance and BalanceTransaction list.",
    sourceTests: "orders/tests.py:1317, tests/test_balance_credit_integration.py:190",
    sourceCode: "payment/services.py:68, payment/models.py:69, clients/services/balance_service.py:120",
  },
  {
    id: "PAY-005",
    area: "Payments",
    priority: "P1",
    scenario: "Cantidad cobrada greater than order total adds excess to client balance",
    preconditions: "Contado order total_amount = 100.00. Client current balance known.",
    steps: step([
      "Complete checkout with cantidad_cobrada = 120.00.",
      "Use a valid payment method for the order total.",
      "Open client detail after payment.",
    ]),
    expected: expect([
      "Payment succeeds.",
      "Order cantidad_cobrada is 120.00.",
      "Client balance increases by 20.00.",
      "BalanceTransaction transaction_type is added_in_order and references the order.",
    ]),
    postChecks: "Verify response shows balance_added/new_client_balance when available.",
    sourceTests: "payment/tests.py:43",
    sourceCode: "payment/services.py:337, clients/services/balance_service.py:59",
  },
  {
    id: "PAY-006",
    area: "Payments",
    priority: "P0",
    scenario: "Cantidad cobrada below order total is rejected",
    preconditions: "Order total_amount = 100.00.",
    steps: step([
      "Attempt checkout with cantidad_cobrada = 99.99.",
      "Submit payment.",
    ]),
    expected: expect([
      "Submission is rejected.",
      "Error states cantidad cobrada cannot be less than order total.",
      "No balance is added and no successful payment should be recorded from this submission.",
    ]),
    postChecks: "Compare payments and balance before/after.",
    sourceTests: "payment/tests.py:35",
    sourceCode: "payment/services.py:33, payment/services.py:337",
  },
  {
    id: "PAY-007",
    area: "Payments",
    priority: "P1",
    scenario: "Invalid settlement payment method is rejected",
    preconditions: "Order exists and user is logged in.",
    steps: step([
      "Submit a payment request with a method outside the allowed set.",
      "Observe the response.",
    ]),
    expected: expect([
      "Payment is rejected with Metodo de pago invalido para este flujo.",
      "No Payment row is persisted.",
    ]),
    postChecks: "Check payment count for the order.",
    sourceTests: "payment/tests.py:153",
    sourceCode: "payment/services.py:12, payment/services.py:68",
  },
  {
    id: "PAY-008",
    area: "Payments",
    priority: "P2",
    scenario: "Checkout notes are persisted on the order",
    preconditions: "Pending order exists.",
    steps: step([
      "Enter an order note during checkout/payment.",
      "Complete or submit the payment request.",
      "Reopen the order.",
    ]),
    expected: expect([
      "Order notes are saved trimmed.",
      "Blank notes are stored as empty/null.",
    ]),
    postChecks: "Check order detail or admin field.",
    sourceTests: "orders/tests.py:333, orders/tests.py:347",
    sourceCode: "payment/services.py:33, orders/views.py:463",
  },
  {
    id: "PAY-009",
    area: "Payments",
    priority: "P1",
    scenario: "Completed pending_credit marker is not counted as money paid",
    preconditions: "Credit order has only a pending_credit payment marker changed to completed and no cash/balance payment.",
    steps: step([
      "Open the order or invoice/payment totals.",
      "Compare order total_paid against total_amount.",
    ]),
    expected: expect([
      "Order total_paid is 0.00 for the pending_credit marker.",
      "Order still appears unpaid until a non-pending_credit completed payment exists.",
    ]),
    postChecks: "Check unpaid order filters and invoice total_payments.",
    sourceTests: "payment/tests.py:284",
    sourceCode: "invoice/models.py:47, invoice/models.py:136, payment/models.py:49",
  },
  {
    id: "BAL-001",
    area: "Balance",
    priority: "P0",
    scenario: "Manual balance deposit updates saldo and audit trail",
    preconditions: "Active client exists. QA user is logged in.",
    steps: step([
      "Open client Add Balance/Gestionar saldo.",
      "Select transaction type Deposito.",
      "Enter amount 200.00 and detailed notes of at least 10 characters.",
      "Submit and open client detail payment history.",
    ]),
    expected: expect([
      "Client balance increases by 200.00.",
      "BalanceTransaction is created with before/after balances, created_by, and notes.",
      "Success message shows updated saldo.",
    ]),
    postChecks: "Verify in BalanceTransaction admin/history.",
    sourceTests: "tests/test_balance_credit_history.py:1",
    sourceCode: "clients/views.py:942, clients/forms.py:12, clients/services/balance_service.py:59",
  },
  {
    id: "BAL-002",
    area: "Balance",
    priority: "P1",
    scenario: "Manual balance deposit requires positive amount and meaningful notes",
    preconditions: "Active client exists.",
    steps: step([
      "Open Add Balance.",
      "Try amount 0.00 or notes shorter than 10 characters.",
      "Submit.",
    ]),
    expected: expect([
      "Form validation blocks submission.",
      "No BalanceTransaction is created.",
      "Client balance remains unchanged.",
    ]),
    postChecks: "Confirm validation messages and no new transaction.",
    sourceTests: "tests/test_balance_credit_history.py:1",
    sourceCode: "clients/forms.py:12, clients/services/balance_service.py:59",
  },
  {
    id: "DEBT-001",
    area: "Debt",
    priority: "P0",
    scenario: "Manual debt payment reduces current debt",
    preconditions: "Client current_debt = 300.00 and credit_limit is set.",
    steps: step([
      "Open client Gestionar credito/pay-credit.",
      "Select Pago de deuda.",
      "Enter amount 100.00, description, and detailed notes.",
      "Submit and open client detail.",
    ]),
    expected: expect([
      "Client current_debt decreases to 200.00.",
      "CreditTransaction transaction_type payment is created with debt_before 300.00 and debt_after 200.00.",
      "Available credit increases by 100.00.",
    ]),
    postChecks: "Verify CreditTransaction and global credit report totals.",
    sourceTests: "tests/test_balance_credit_history.py:1",
    sourceCode: "clients/views.py:854, clients/forms.py:64, clients/services/balance_service.py:261",
  },
  {
    id: "DEBT-002",
    area: "Debt",
    priority: "P0",
    scenario: "Pay debt from client balance updates both ledgers",
    preconditions: "Client balance = 150.00 and current_debt = 200.00.",
    steps: step([
      "Open Gestionar credito/pay-credit.",
      "Select Pago con Saldo.",
      "Enter amount 100.00 with valid description and notes.",
      "Submit.",
    ]),
    expected: expect([
      "Client balance decreases to 50.00.",
      "Client current_debt decreases to 100.00.",
      "BalanceTransaction transaction_type payment is created.",
      "CreditTransaction transaction_type payment_from_balance is created.",
    ]),
    postChecks: "Check both history sections on client detail.",
    sourceTests: "tests/test_balance_credit_history.py:1",
    sourceCode: "clients/views.py:854, clients/forms.py:64, clients/services/balance_service.py:488",
  },
  {
    id: "DEBT-003",
    area: "Debt",
    priority: "P1",
    scenario: "Pay debt from balance rejects insufficient saldo",
    preconditions: "Client balance = 50.00 and current_debt = 200.00.",
    steps: step([
      "Open Gestionar credito/pay-credit.",
      "Select Pago con Saldo.",
      "Enter amount 100.00.",
      "Submit.",
    ]),
    expected: expect([
      "Form or service blocks submission with Saldo insuficiente.",
      "Client balance and debt remain unchanged.",
      "No paired ledger transactions are created.",
    ]),
    postChecks: "Check BalanceTransaction and CreditTransaction counts.",
    sourceTests: "tests/test_balance_credit_history.py:1",
    sourceCode: "clients/forms.py:64, clients/services/balance_service.py:488",
  },
  {
    id: "DEBT-004",
    area: "Debt",
    priority: "P1",
    scenario: "Debt payment cannot exceed current debt",
    preconditions: "Client current_debt = 80.00.",
    steps: step([
      "Open Gestionar credito/pay-credit.",
      "Select Pago de deuda or Condonacion de deuda.",
      "Enter amount 100.00 and submit.",
    ]),
    expected: expect([
      "Validation blocks submission because amount exceeds current debt.",
      "Debt remains 80.00.",
    ]),
    postChecks: "Confirm field-level amount error.",
    sourceTests: "tests/test_balance_credit_history.py:1",
    sourceCode: "clients/forms.py:64",
  },
  {
    id: "DEBT-005",
    area: "Debt",
    priority: "P1",
    scenario: "Credit limit change creates audit transaction",
    preconditions: "Client credit_limit = 500.00 and current_debt = 100.00.",
    steps: step([
      "Open Gestionar credito/pay-credit.",
      "Select Cambio de limite de credito.",
      "Enter new credit limit 800.00 and valid notes.",
      "Submit.",
    ]),
    expected: expect([
      "Client credit_limit updates to 800.00.",
      "CreditTransaction transaction_type limit_change is created.",
      "CreditTransaction records credit_limit_before 500.00 and credit_limit_after 800.00.",
    ]),
    postChecks: "Check client credit panel and credit report available credit.",
    sourceTests: "tests/test_balance_credit_history.py:1",
    sourceCode: "clients/views.py:854, clients/services/balance_service.py:431",
  },
  {
    id: "CRED-001",
    area: "Credit Orders",
    priority: "P0",
    scenario: "Register credit order with no balance",
    preconditions: "Client balance = 0.00, credit_limit = 500.00, current_debt = 0.00, can_pay_with_credit = true. Order type credito, total 100.00.",
    steps: step([
      "Open order checkout.",
      "Select order type credito.",
      "Finish order without selecting a cash payment method.",
      "Open client detail and order payments.",
    ]),
    expected: expect([
      "Order is marked COMPLETED.",
      "A Payment marker exists with method pending_credit, status pending, amount 100.00.",
      "Client current_debt increases to 100.00.",
      "CreditTransaction purchase exists and references the order/payment.",
    ]),
    postChecks: "Confirm available credit decreases to 400.00.",
    sourceTests: "payment/tests.py:92, payment/tests.py:344",
    sourceCode: "payment/services.py:403, payment/services.py:423, clients/services/balance_service.py:184",
  },
  {
    id: "CRED-002",
    area: "Credit Orders",
    priority: "P0",
    scenario: "Credit order uses saldo first and credits only the remainder",
    preconditions: "Client balance = 30.00, credit_limit = 100.00, current_debt = 0.00. Credit order total = 50.00.",
    steps: step([
      "Create a credit order for 50.00.",
      "Finish/register the credit order.",
      "Open payments and ledgers.",
    ]),
    expected: expect([
      "Balance payment of 30.00 is created and completed.",
      "pending_credit marker is created for 20.00.",
      "Client balance becomes 0.00.",
      "Client current_debt becomes 20.00.",
    ]),
    postChecks: "Check both balance and credit transaction references.",
    sourceTests: "orders/tests.py:1443, payment/tests.py:396",
    sourceCode: "payment/services.py:423, payment/services.py:68, clients/services/balance_service.py:184",
  },
  {
    id: "CRED-003",
    area: "Credit Orders",
    priority: "P1",
    scenario: "Credit order fully covered by saldo creates no debt",
    preconditions: "Client balance = 150.00 and credit order total = 100.00.",
    steps: step([
      "Create and finish an order with type credito.",
      "Open order payments and client detail.",
    ]),
    expected: expect([
      "Order completes with balance payment only.",
      "No pending_credit marker is left pending.",
      "Client current_debt remains unchanged.",
      "Response/message says order paid completely with available balance.",
    ]),
    postChecks: "Confirm no CreditTransaction purchase for this order.",
    sourceTests: "orders/tests.py:1423",
    sourceCode: "payment/services.py:423",
  },
  {
    id: "CRED-004",
    area: "Credit Orders",
    priority: "P0",
    scenario: "Emergency credit stop blocks new credit sale",
    preconditions: "Client balance = 30.00, credit_limit = 200.00, current_debt = 0.00, can_pay_with_credit = false. Credit order total = 100.00.",
    steps: step([
      "Create a credit order for 100.00.",
      "Attempt to finish/register as credito.",
    ]),
    expected: expect([
      "Request is rejected with Cliente no puede pagar con credito.",
      "Client balance remains 30.00.",
      "Client current_debt remains 0.00.",
      "No Payment or CreditTransaction is created.",
    ]),
    postChecks: "This should block even though the numeric credit limit is available.",
    sourceTests: "payment/tests.py:316, clients/tests_credit_management.py:459",
    sourceCode: "clients/models.py:199, clients/services/balance_service.py:184, payment/services.py:423",
  },
  {
    id: "CRED-005",
    area: "Credit Orders",
    priority: "P0",
    scenario: "Credit sale cannot exceed hard limit after applying saldo",
    preconditions: "Client balance = 10.00, credit_limit = 100.00, current_debt = 80.00. Credit order total = 50.00.",
    steps: step([
      "Attempt to register the order as credito.",
      "Observe error and financial state.",
    ]),
    expected: expect([
      "Request is rejected because sale exceeds credit limit.",
      "Client balance remains 10.00 and current_debt remains 80.00.",
      "No payment markers are created.",
    ]),
    postChecks: "Check the available credit shown to the user.",
    sourceTests: "payment/tests.py:396, clients/tests_credit_management.py:478",
    sourceCode: "clients/services/balance_service.py:184, payment/services.py:423",
  },
  {
    id: "CRED-006",
    area: "Credit Orders",
    priority: "P1",
    scenario: "Overdue credit is reported but does not block new credit when limit is available",
    preconditions: "Client has overdue credit purchase for 100.00, credit_limit = 500.00, current_debt = 100.00, can_pay_with_credit = true.",
    steps: step([
      "Confirm client detail/report shows overdue credit.",
      "Create a new credit order for 50.00.",
      "Register it as credito.",
    ]),
    expected: expect([
      "New credit order succeeds.",
      "Client current_debt becomes 150.00.",
      "New pending_credit marker exists for 50.00.",
      "Overdue status remains visible for the older order.",
    ]),
    postChecks: "Check client detail overdue section and global credit report.",
    sourceTests: "payment/tests.py:344, clients/tests_credit_management.py:497",
    sourceCode: "clients/services/pending_payment_service.py:94, payment/services.py:423",
  },
  {
    id: "CRED-007",
    area: "Credit Orders",
    priority: "P1",
    scenario: "Credit order registration is idempotent when pending marker already exists",
    preconditions: "Credit order already has a pending_credit payment marker.",
    steps: step([
      "Submit/register the same credit order again.",
      "Check payments and debt.",
    ]),
    expected: expect([
      "Response says the order already has a pending liquidation record.",
      "No duplicate pending_credit payment is created.",
      "Debt is not increased a second time.",
    ]),
    postChecks: "Compare Payment and CreditTransaction counts before and after.",
    sourceTests: "payment/tests.py:92",
    sourceCode: "payment/services.py:423",
  },
  {
    id: "CRED-008",
    area: "Credit Orders",
    priority: "P0",
    scenario: "Settle pending credit order with exact amount",
    preconditions: "Credit order has pending_credit amount 1000.00. Client current_debt = 1000.00.",
    steps: step([
      "Open the pay screen for the credit order.",
      "Submit amount 1000.00 with cash or bank transfer.",
      "Open client detail and order payments.",
    ]),
    expected: expect([
      "A completed settlement payment is created.",
      "Client current_debt becomes 0.00.",
      "Available credit is restored.",
      "pending_credit marker status changes to completed.",
      "CreditTransaction payment references the order and settlement payment.",
    ]),
    postChecks: "Order should now appear paid because non-pending_credit payment covers it.",
    sourceTests: "payment/tests.py:205, payment/tests.py:294",
    sourceCode: "payment/services.py:108, orders/views.py:113, clients/services/balance_service.py:261",
  },
  {
    id: "CRED-009",
    area: "Credit Orders",
    priority: "P0",
    scenario: "Settle pending credit with wrong amount is rejected",
    preconditions: "Credit order pending_credit amount = 1000.00.",
    steps: step([
      "Open pay screen for the credit order.",
      "Submit amount 900.00.",
    ]),
    expected: expect([
      "Payment is rejected with message that payment must cover pending balance.",
      "No new cash/bank payment is created.",
      "pending_credit remains pending.",
      "Debt remains unchanged.",
    ]),
    postChecks: "Verify order payments count and client debt.",
    sourceTests: "payment/tests.py:272",
    sourceCode: "payment/services.py:108",
  },
  {
    id: "CRED-010",
    area: "Credit Orders",
    priority: "P1",
    scenario: "Existing matching settlement payment is reconciled without duplication",
    preconditions: "Credit order has pending_credit 1000.00 and an existing completed cash payment 1000.00 that has not reduced debt.",
    steps: step([
      "Run/submit the settlement flow for amount 1000.00.",
      "Open the order payments.",
    ]),
    expected: expect([
      "Existing payment is reused.",
      "No duplicate cash payment is created.",
      "Debt is reduced to 0.00.",
      "pending_credit marker is completed.",
    ]),
    postChecks: "Check that only one cash payment exists for the order.",
    sourceTests: "payment/tests.py:222",
    sourceCode: "payment/services.py:108, payment/services.py:163",
  },
  {
    id: "CRED-011",
    area: "Credit Orders",
    priority: "P1",
    scenario: "Mismatched existing settlement payment requires manual review",
    preconditions: "Credit order pending_credit = 1000.00 and existing completed cash payment = 900.00.",
    steps: step([
      "Attempt to settle the credit order.",
      "Observe the response/error.",
    ]),
    expected: expect([
      "Flow raises/returns a manual review error.",
      "Client debt remains unchanged.",
      "No additional payment is created.",
    ]),
    postChecks: "Escalate to engineering or finance ops with order/payment IDs.",
    sourceTests: "payment/tests.py:249",
    sourceCode: "payment/services.py:163",
  },
  {
    id: "CRED-012",
    area: "Credit Orders",
    priority: "P2",
    scenario: "Legacy credit migration dry-run and apply behavior",
    preconditions: "A legacy order has type contado and a completed Payment with method credit.",
    steps: step([
      "Run migrate_legacy_credit_orders without --apply in a safe QA environment.",
      "Confirm no records change.",
      "Run again with --apply.",
      "Inspect order and payment.",
    ]),
    expected: expect([
      "Dry run reports no writes.",
      "--apply changes order.type to credito.",
      "Legacy payment changes to method pending_credit and status pending.",
    ]),
    postChecks: "Only run this in a disposable QA database.",
    sourceTests: "payment/tests.py:431, payment/tests.py:457",
    sourceCode: "orders/management/commands/migrate_legacy_credit_orders.py:22",
  },
  {
    id: "CFG-001",
    area: "Credit Config",
    priority: "P0",
    scenario: "Emergency stop checkbox semantics are inverted correctly",
    preconditions: "Client can_pay_with_credit = true and credit_limit = 500.00.",
    steps: step([
      "Open client edit > credit tab.",
      "Check the field labelled Cliente no puede pagar con credito.",
      "Save.",
      "Open the client again.",
    ]),
    expected: expect([
      "When checkbox is checked, persisted can_pay_with_credit is false.",
      "When checkbox is unchecked, persisted can_pay_with_credit is true.",
      "Credit sale attempts respect the persisted value.",
    ]),
    postChecks: "Do CRED-004 after enabling the emergency stop.",
    sourceTests: "clients/tests_credit_management.py:75, clients/tests_credit_management.py:95",
    sourceCode: "clients/forms.py:157, clients/models.py:199",
  },
  {
    id: "CFG-002",
    area: "Credit Config",
    priority: "P1",
    scenario: "Invoice-due credit terms require recurring billing",
    preconditions: "Corporate client exists with requires_billing false.",
    steps: step([
      "Open credit configuration.",
      "Select Vencimiento posterior a factura/invoice_due.",
      "Attempt to save without enabling recurring billing.",
      "Then enable recurring billing and save invoice_due.",
      "Try disabling recurring billing while invoice_due remains configured.",
    ]),
    expected: expect([
      "invoice_due cannot be saved unless requires_billing is true.",
      "Recurring billing cannot be disabled while invoice_due credit terms are active.",
    ]),
    postChecks: "Verify validation message mentions billing/facturacion requirement.",
    sourceTests: "clients/tests_credit_management.py:127, clients/tests_credit_management.py:143",
    sourceCode: "clients/models.py:141, clients/models.py:606, clients/views.py:262",
  },
  {
    id: "CFG-003",
    area: "Credit Config",
    priority: "P1",
    scenario: "New branch copies corporate credit policy but not ledger state",
    preconditions: "Corporate client has credit_limit 750.00, current_debt 320.00, balance 125.00, can_pay_with_credit false, and credit config cutoff_day 15.",
    steps: step([
      "Create a branch under that corporate.",
      "Open branch detail/edit credit tab.",
    ]),
    expected: expect([
      "Branch credit_limit is 750.00.",
      "Branch can_pay_with_credit is false.",
      "Branch current_debt is 0.00 and balance is 0.00.",
      "Branch credit config copies payment term, cutoff day, and max payment days.",
    ]),
    postChecks: "Confirm branch credit_override_enabled defaults false.",
    sourceTests: "clients/tests_credit_management.py:170",
    sourceCode: "clients/services/client_service.py:51, clients/views.py:216",
  },
  {
    id: "CFG-004",
    area: "Credit Config",
    priority: "P1",
    scenario: "Branch without credit override is read-only for credit policy",
    preconditions: "Branch belongs to corporate and credit_override_enabled is false.",
    steps: step([
      "Open branch edit > credit tab.",
      "Attempt to change credit_limit through the UI or PATCH endpoint.",
    ]),
    expected: expect([
      "UI shows credit settings as read-only and points to corporate management.",
      "PATCH/API update is rejected with 400.",
      "Branch credit_limit and can_pay_with_credit remain unchanged.",
    ]),
    postChecks: "Use branch with override disabled only.",
    sourceTests: "clients/tests_credit_management.py:301, clients/tests_credit_management.py:314, clients/tests_credit_management.py:383",
    sourceCode: "clients/views.py:121, clients/views.py:262, clients/services/client_service.py:89",
  },
  {
    id: "CFG-005",
    area: "Credit Config",
    priority: "P2",
    scenario: "Branch with credit override can edit credit policy",
    preconditions: "Branch has credit_override_enabled true.",
    steps: step([
      "Open branch edit > credit tab.",
      "Change credit_limit to 500.00 and save.",
      "Optionally PATCH credit_limit/can_pay_with_credit.",
    ]),
    expected: expect([
      "UI saves the branch-specific credit policy.",
      "PATCH/API can update credit fields.",
      "Corporate policy is not modified by the branch edit.",
    ]),
    postChecks: "Compare branch and corporate values.",
    sourceTests: "clients/tests_credit_management.py:331, clients/tests_credit_management.py:398",
    sourceCode: "clients/views.py:262, clients/services/client_service.py:89",
  },
  {
    id: "CFG-006",
    area: "Credit Config",
    priority: "P1",
    scenario: "Monthly cutoff due dates handle cutoff day and month end",
    preconditions: "Client credit config payment_term_type monthly_cutoff.",
    steps: step([
      "Set cutoff_day to 20 and create credit sale dated 2026-06-21.",
      "Check due date.",
      "Create another sale dated 2026-06-20.",
      "Set cutoff_day last_day or 30 in February and check due date.",
    ]),
    expected: expect([
      "Sale after cutoff is due 2026-07-20.",
      "Sale on cutoff is due 2026-06-20.",
      "last_day uses actual month end.",
      "Numeric cutoff beyond month end clamps to actual month end.",
    ]),
    postChecks: "Client detail nearest due date should reflect these dates when open credit exists.",
    sourceTests: "clients/tests_credit_terms.py:13, clients/tests_credit_terms.py:18, clients/tests_credit_terms.py:23, clients/tests_credit_terms.py:28",
    sourceCode: "clients/services/pending_payment_service.py:27, clients/services/pending_payment_service.py:40",
  },
  {
    id: "CFG-007",
    area: "Credit Config",
    priority: "P1",
    scenario: "Invoice-due credit waits for invoice emission then adds max days",
    preconditions: "Client uses invoice_due with max_payment_days = 30.",
    steps: step([
      "Create a credit order without an invoice.",
      "Check client credit report/client detail due date.",
      "Create or link invoice with emitted_at 2026-06-10.",
      "Check due date again.",
    ]),
    expected: expect([
      "Uninvoiced order has no due date and is not overdue.",
      "After invoice emission, due date is 2026-07-10.",
    ]),
    postChecks: "Use client credit report detailed page.",
    sourceTests: "clients/tests_credit_terms.py:33, clients/tests_credit_terms.py:46, clients/tests_credit_report_service.py:164",
    sourceCode: "clients/services/pending_payment_service.py:40, clients/services/credit_report_service.py:143",
  },
  {
    id: "INV-001",
    area: "Invoices",
    priority: "P0",
    scenario: "Invoiceable orders list includes only same-client completed unbilled orders",
    preconditions: "Client A has completed unbilled orders, pending orders, and an already-billed order. Client B has completed orders.",
    steps: step([
      "Open invoice edit/create link flow for Client A.",
      "Open the order dropdown or invoiceable-orders AJAX endpoint.",
    ]),
    expected: expect([
      "Client A completed unbilled orders appear.",
      "Client B orders do not appear.",
      "Pending orders do not appear.",
      "Orders linked to any invoice do not appear.",
    ]),
    postChecks: "Check invoiceable orders endpoint response if needed.",
    sourceTests: "invoice/tests.py:38, invoice/tests.py:259, invoice/tests.py:274, invoice/tests.py:296",
    sourceCode: "invoice/services.py:352, invoice/views.py:15",
  },
  {
    id: "INV-002",
    area: "Invoices",
    priority: "P1",
    scenario: "Editing an existing invoice link preserves the current linked order",
    preconditions: "Invoice has an existing InvoiceOrderLink to an order that would otherwise be excluded.",
    steps: step([
      "Open the invoice edit screen.",
      "Edit the existing linked order row.",
      "Check the dropdown options.",
    ]),
    expected: expect([
      "The current linked order remains selectable while editing.",
      "Other already-linked orders remain excluded.",
    ]),
    postChecks: "This protects admin edits from losing the current selection.",
    sourceTests: "invoice/tests.py:105, invoice/tests.py:309",
    sourceCode: "invoice/services.py:352, invoice/static/admin/js/billing_record_inline_orders.js:117",
  },
  {
    id: "INV-003",
    area: "Invoices",
    priority: "P0",
    scenario: "Manual invoice amount cap blocks linked orders that exceed the invoice amount",
    preconditions: "Manual invoice auto_amount false, amount 100.00. Existing linked order 80.00. New order 30.00.",
    steps: step([
      "Open the manual invoice edit screen.",
      "Try linking the new 30.00 order.",
    ]),
    expected: expect([
      "Form blocks the link because linked order total would be 110.00.",
      "No InvoiceOrderLink is created for the new order.",
      "Error explains that the sum exceeds the invoice amount.",
    ]),
    postChecks: "Check linked orders table remains unchanged.",
    sourceTests: "invoice/tests.py:130",
    sourceCode: "invoice/services.py:265, invoice/services.py:314",
  },
  {
    id: "INV-004",
    area: "Invoices",
    priority: "P1",
    scenario: "Manual invoice cap allows exact boundary",
    preconditions: "Manual invoice amount 100.00. Existing linked order 80.00. New completed order 20.00.",
    steps: step([
      "Open invoice edit.",
      "Link the 20.00 order.",
    ]),
    expected: expect([
      "Form saves successfully.",
      "Linked order total equals invoice amount 100.00.",
    ]),
    postChecks: "Check invoice linked orders sum.",
    sourceTests: "invoice/tests.py:187",
    sourceCode: "invoice/services.py:314",
  },
  {
    id: "INV-005",
    area: "Invoices",
    priority: "P0",
    scenario: "Auto amount invoice derives amount from linked orders",
    preconditions: "Auto invoice initially links order 50.00.",
    steps: step([
      "Create invoice from completed orders or enable auto_amount.",
      "Add another completed order worth 25.00.",
      "Save invoice edit.",
    ]),
    expected: expect([
      "auto_amount invoice accepts linked orders even when prior amount would have been exceeded.",
      "Invoice amount syncs to 75.00.",
      "If all links are removed, invoice amount syncs to 0.00.",
    ]),
    postChecks: "Check invoice amount after save and after removing links.",
    sourceTests: "invoice/tests.py:159, invoice/tests.py:469, invoice/tests.py:485",
    sourceCode: "invoice/services.py:476, invoice/services.py:534, invoice/views.py:142",
  },
  {
    id: "INV-006",
    area: "Invoices",
    priority: "P0",
    scenario: "Bulk create invoice from completed same-client orders",
    preconditions: "Admin user. Two completed orders for same invoice-ready corporate client: 50.00 and 30.00.",
    steps: step([
      "Open admin orders dashboard.",
      "Select both completed orders.",
      "Choose bulk action Crear factura.",
      "Submit.",
    ]),
    expected: expect([
      "Redirects to invoice edit screen.",
      "Invoice is created for 80.00.",
      "Invoice has two InvoiceOrderLink rows.",
      "identifier and folio are BORRADOR placeholders for later update.",
    ]),
    postChecks: "Check invoice linked order IDs.",
    sourceTests: "orders/tests.py:1043, invoice/tests.py:413, invoice/tests.py:426",
    sourceCode: "orders/views.py:253, invoice/services.py:476",
  },
  {
    id: "INV-007",
    area: "Invoices",
    priority: "P0",
    scenario: "Bulk create invoice rejects non-completed orders",
    preconditions: "Selected orders include one completed and one pending order.",
    steps: step([
      "Open admin orders dashboard.",
      "Select the mixed-status orders.",
      "Choose Crear factura and submit.",
    ]),
    expected: expect([
      "No invoice is created.",
      "Message says only completed orders can be invoiced.",
      "Pending order ID is included in the error context.",
    ]),
    postChecks: "Check Invoice count for the client.",
    sourceTests: "orders/tests.py:1062",
    sourceCode: "orders/views.py:253",
  },
  {
    id: "INV-008",
    area: "Invoices",
    priority: "P0",
    scenario: "Bulk create invoice rejects orders from different corporates",
    preconditions: "Selected completed orders belong to different corporate owners.",
    steps: step([
      "Select completed orders across different corporate clients.",
      "Run Crear factura.",
    ]),
    expected: expect([
      "No invoice is created.",
      "Error says all selected orders must belong to the same corporate client.",
    ]),
    postChecks: "Include branch/corporate combinations in this test.",
    sourceTests: "invoice/tests.py:445",
    sourceCode: "invoice/services.py:476, orders/views.py:253",
  },
  {
    id: "INV-009",
    area: "Invoices",
    priority: "P0",
    scenario: "Invoice generation rejects missing fiscal data or fiscal address",
    preconditions: "Client has completed orders but lacks RFC/razon_social or active billing address.",
    steps: step([
      "Run Crear factura from admin orders.",
      "Repeat with missing RFC/razon_social.",
      "Repeat with missing active billing address.",
    ]),
    expected: expect([
      "No invoice is created.",
      "Error identifies missing RFC/Razon social or fiscal address.",
      "For branches, the corporate owner is named when corporate data is missing.",
    ]),
    postChecks: "Check that no partial invoice/link rows were created.",
    sourceTests: "orders/tests.py:1076, orders/tests.py:1093, invoice/tests.py:455",
    sourceCode: "invoice/services.py:47, invoice/services.py:476",
  },
  {
    id: "INV-010",
    area: "Invoices",
    priority: "P1",
    scenario: "Branch invoice generation validates corporate fiscal data, not branch-owned data",
    preconditions: "Branch has its own fiscal data/address, but its corporate client is missing RFC or billing address.",
    steps: step([
      "Select a completed branch order.",
      "Run Crear factura.",
    ]),
    expected: expect([
      "Invoice creation is rejected.",
      "Error references the corporate client as the required billing owner.",
      "Branch-owned fiscal data does not bypass corporate validation.",
    ]),
    postChecks: "Check branch and corporate setup before test.",
    sourceTests: "orders/tests.py:1121, clients/tests.py:140, clients/tests.py:173",
    sourceCode: "invoice/services.py:23, invoice/services.py:47",
  },
  {
    id: "INV-011",
    area: "Invoices",
    priority: "P1",
    scenario: "Invoice balance snapshot separates available capacity from unpaid balance",
    preconditions: "Invoice amount 1000.00 linked to orders totaling 800.00. Payments include cash 600.00 and pending_credit 50.00.",
    steps: step([
      "Open invoice list/dashboard or run the invoice balance snapshot view/service if exposed.",
      "Compare linked order totals and completed non-credit payments.",
    ]),
    expected: expect([
      "Available capacity is 200.00 because invoice amount exceeds linked order totals.",
      "Unpaid balance is 400.00 because pending_credit is excluded from paid total.",
      "A fully used/paid invoice is not counted in either bucket.",
    ]),
    postChecks: "Use invoice list amount, total payments, and pending amount columns.",
    sourceTests: "invoice/tests.py:565",
    sourceCode: "invoice/services.py:97, invoice/models.py:47, invoice/models.py:136",
  },
  {
    id: "INV-012",
    area: "Invoices",
    priority: "P2",
    scenario: "Invoice admin create and edit screens persist fields and links",
    preconditions: "Staff/admin user and invoice-ready client.",
    steps: step([
      "Open Administrador > Facturas > Nueva Factura.",
      "Create invoice with client, serie, folio, amount 150.00.",
      "Open edit screen and link a completed order.",
    ]),
    expected: expect([
      "Create redirects to edit page.",
      "Invoice exists with entered identifier/folio/amount.",
      "Linked order appears in the invoice linked sales table.",
    ]),
    postChecks: "Upload file field can be tested separately if QA has PDF/XML sample.",
    sourceTests: "invoice/tests.py:523, invoice/tests.py:536, invoice/tests.py:542",
    sourceCode: "invoice/views.py:120, invoice/views.py:142",
  },
  {
    id: "CAN-001",
    area: "Cancellations",
    priority: "P0",
    scenario: "Cancel pending order marks it cancelled without deleting items",
    preconditions: "Pending order exists with at least one item.",
    steps: step([
      "Open order screen.",
      "Click cancel order and confirm.",
      "Open order admin/detail.",
    ]),
    expected: expect([
      "Order status becomes CANCELLED.",
      "OrderProduct rows are still present for audit/history.",
      "No cancellation review flag is set.",
    ]),
    postChecks: "Check order list filters active/cancelled.",
    sourceTests: "orders/tests.py:656, orders/tests.py:929",
    sourceCode: "orders/services.py:329, orders/services.py:398, orders/views.py:528",
  },
  {
    id: "CAN-002",
    area: "Cancellations",
    priority: "P0",
    scenario: "Cancel completed cash order reverses external payment status",
    preconditions: "Completed order has completed cash payment.",
    steps: step([
      "Cancel the completed order.",
      "Open order payments.",
    ]),
    expected: expect([
      "Order status becomes CANCELLED.",
      "Cash payment status becomes reversed.",
      "Client balance and debt do not change for cash-only payment.",
    ]),
    postChecks: "Check reports do not count reversed payment buckets.",
    sourceTests: "orders/tests.py:673, report/tests.py:437",
    sourceCode: "orders/services.py:323, orders/services.py:329, report/views.py:45",
  },
  {
    id: "CAN-003",
    area: "Cancellations",
    priority: "P0",
    scenario: "Cancel balance-paid order restores saldo",
    preconditions: "Completed order has balance payment 40.00 and client balance was reduced from 100.00 to 60.00.",
    steps: step([
      "Cancel the completed order.",
      "Open client detail history.",
    ]),
    expected: expect([
      "Client balance returns to 100.00.",
      "Original balance payment is marked reversed.",
      "BalanceTransaction transaction_type payment_reversal exists and references the payment.",
    ]),
    postChecks: "Confirm order is CANCELLED.",
    sourceTests: "orders/tests.py:554, orders/tests.py:693",
    sourceCode: "clients/services/balance_service.py:331, orders/services.py:267",
  },
  {
    id: "CAN-004",
    area: "Cancellations",
    priority: "P0",
    scenario: "Cancel open credit order reverses credit purchase",
    preconditions: "Completed credito order has pending_credit marker pending and CreditTransaction purchase 50.00. Client current_debt = 50.00.",
    steps: step([
      "Cancel the credit order.",
      "Open client credit history and order payments.",
    ]),
    expected: expect([
      "Client current_debt becomes 0.00.",
      "pending_credit payment status becomes reversed.",
      "CreditTransaction purchase_reversal exists for the order.",
    ]),
    postChecks: "Check available credit is restored.",
    sourceTests: "orders/tests.py:589, orders/tests.py:721",
    sourceCode: "clients/services/balance_service.py:367, orders/services.py:302",
  },
  {
    id: "CAN-005",
    area: "Cancellations",
    priority: "P0",
    scenario: "Cancel settled credit order reverses settlement payment and purchase",
    preconditions: "Credit order has pending_credit completed, cash settlement completed, purchase and payment credit transactions. Client debt currently 0.00.",
    steps: step([
      "Cancel the settled credit order.",
      "Open order payments and client credit transactions.",
    ]),
    expected: expect([
      "pending_credit and cash settlement payments become reversed.",
      "A payment_reversal transaction restores the settled debt.",
      "A purchase_reversal transaction reverses the original credit purchase.",
      "Final client current_debt remains 0.00.",
    ]),
    postChecks: "Order status is CANCELLED and credit report no longer inflates open credit.",
    sourceTests: "orders/tests.py:607, orders/tests.py:757, clients/tests_credit_report_service.py:186",
    sourceCode: "orders/services.py:281, orders/services.py:302, orders/services.py:323",
  },
  {
    id: "CAN-006",
    area: "Cancellations",
    priority: "P0",
    scenario: "Cancel order with spent added-in-order balance requires review",
    preconditions: "Order cantidad_cobrada added 50.00 to client balance, but client current balance is now 0.00.",
    steps: step([
      "Attempt to cancel the completed order.",
      "Open order list/admin order record.",
    ]),
    expected: expect([
      "Cancellation fails with review_required true.",
      "Order remains COMPLETED.",
      "Order cancellation_review_required is true and reason mentions saldo.",
      "Review badge appears on order list/admin orders.",
    ]),
    postChecks: "Finance/admin must manually resolve before retrying.",
    sourceTests: "orders/tests.py:819, orders/tests.py:1163, orders/tests.py:1179",
    sourceCode: "orders/services.py:237, orders/services.py:329, orders/views.py:305",
  },
  {
    id: "CAN-007",
    area: "Cancellations",
    priority: "P0",
    scenario: "Cancel order linked to invoice requires review",
    preconditions: "Completed order is linked to an invoice.",
    steps: step([
      "Attempt to cancel the order.",
      "Open order list and client detail invoices.",
    ]),
    expected: expect([
      "Cancellation fails with review_required true.",
      "Order remains COMPLETED.",
      "Review reason mentions factura.",
      "Review badge appears in user/admin order lists.",
    ]),
    postChecks: "Invoice link must be reviewed before cancellation can proceed.",
    sourceTests: "orders/tests.py:844, orders/tests.py:959",
    sourceCode: "orders/services.py:329, orders/views.py:528",
  },
  {
    id: "CAN-008",
    area: "Cancellations",
    priority: "P2",
    scenario: "Successful cancellation retry clears review metadata",
    preconditions: "Order has cancellation_review_required true from a previous blocked attempt, and the blocker has been resolved.",
    steps: step([
      "Retry cancellation after resolving the issue.",
      "Open the order record.",
    ]),
    expected: expect([
      "Cancellation succeeds.",
      "Order status becomes CANCELLED.",
      "cancellation_review_required, reason, requested_at, and requested_by are cleared.",
    ]),
    postChecks: "Order no longer appears under REVIEW_REQUIRED filter.",
    sourceTests: "orders/tests.py:864, orders/tests.py:1195",
    sourceCode: "orders/services.py:230, orders/services.py:329",
  },
  {
    id: "REP-001",
    area: "Reports",
    priority: "P0",
    scenario: "Global credit report shows credit columns and correct sort order",
    preconditions: "Tempano active client has current_debt 17000.00, credit_limit 20000.00, overdue amount 9700.00. Vigor active client has current_debt 8300.00 and no overdue. Inactive and zero-credit clients also exist.",
    steps: step([
      "Open Reportes > Credito global.",
      "Review rows and totals.",
    ]),
    expected: expect([
      "Columns include Credito vigente, Linea de credito autorizada, Disponible, and Monto vencido.",
      "Active credit/debt clients appear.",
      "Inactive and no-credit/no-debt clients are excluded.",
      "Rows sort by overdue amount descending, then current debt descending.",
    ]),
    postChecks: "Use search filter if dataset is large.",
    sourceTests: "clients/tests_credit_report_service.py:73, report/tests.py:506",
    sourceCode: "clients/services/credit_report_service.py:261, report/views.py:235",
  },
  {
    id: "REP-002",
    area: "Reports",
    priority: "P0",
    scenario: "Client credit report splits invoiced and uninvoiced open credit",
    preconditions: "Client has two invoiced credit orders totaling 9700.00 and one uninvoiced credit order 4500.00. Current debt = 14200.00.",
    steps: step([
      "Open client detail and click Reporte de credito.",
      "Review the detailed report sections.",
    ]),
    expected: expect([
      "Invoiced credit total is 9700.00.",
      "Uninvoiced credit total is 4500.00.",
      "Invoice item shows the invoice identifier/folio.",
      "No reconciliation warning appears when current_debt equals open credit total.",
    ]),
    postChecks: "Check the client detail link to the report exists.",
    sourceTests: "clients/tests_credit_report_service.py:120, report/tests.py:528, report/tests.py:556",
    sourceCode: "clients/services/credit_report_service.py:250, clients/views.py:608, report/views.py:290",
  },
  {
    id: "REP-003",
    area: "Reports",
    priority: "P1",
    scenario: "Invoice-due uninvoiced credit is not overdue until invoice emission",
    preconditions: "Client uses invoice_due. Old credit order exists but no invoice link with emmited_at.",
    steps: step([
      "Open global credit report and client credit report.",
      "Inspect overdue amount and order due date.",
    ]),
    expected: expect([
      "Global report overdue amount is 0.00 for this client/order.",
      "Client report shows no due date for the uninvoiced order.",
      "Uninvoiced order is not marked overdue.",
    ]),
    postChecks: "Then link invoice/emission date and rerun CFG-007.",
    sourceTests: "clients/tests_credit_report_service.py:164",
    sourceCode: "clients/services/pending_payment_service.py:40, clients/services/credit_report_service.py:143",
  },
  {
    id: "REP-004",
    area: "Reports",
    priority: "P1",
    scenario: "Cancelled orders and reversed payments do not inflate open credit or payment reports",
    preconditions: "Client has active credit order 100.00, canceled credit order 500.00, and reversed cash payment 100.00.",
    steps: step([
      "Open client credit report.",
      "Open orders/payment reports filtered by payment method if applicable.",
    ]),
    expected: expect([
      "Open credit total remains 100.00.",
      "Overdue amount only includes active unpaid order.",
      "Reversed payment is ignored in payment-method filtered reports.",
    ]),
    postChecks: "Check canceled order is excluded by default from reports.",
    sourceTests: "clients/tests_credit_report_service.py:186, report/tests.py:437",
    sourceCode: "clients/services/credit_report_service.py:100, report/views.py:39, report/views.py:45",
  },
  {
    id: "REP-005",
    area: "Reports",
    priority: "P2",
    scenario: "Global credit report CSV export contains required columns",
    preconditions: "Credit report has at least one client row.",
    steps: step([
      "Open global credit report.",
      "Click export CSV.",
      "Open the downloaded CSV.",
    ]),
    expected: expect([
      "CSV headers are Cliente, Credito vigente, Linea de credito autorizada, Disponible, Monto vencido.",
      "Currency values are exported as raw decimal strings with two decimals.",
      "Search filters are preserved in export link.",
    ]),
    postChecks: "Validate with a client named Tempano if using test dataset.",
    sourceTests: "report/tests.py:520",
    sourceCode: "report/views.py:200, report/views.py:262",
  },
  {
    id: "REP-006",
    area: "Reports",
    priority: "P2",
    scenario: "Client list credits mode filters clients with debt",
    preconditions: "At least one client has current_debt > 0 and at least one active client has zero debt.",
    steps: step([
      "Open clients list with mode=credits.",
      "Use search and pagination.",
    ]),
    expected: expect([
      "Only clients with current_debt greater than 0 appear.",
      "Search and pagination preserve mode=credits.",
      "Page title/subtitle indicate credit collection context.",
    ]),
    postChecks: "Use client detail for selected debt clients.",
    sourceTests: "clients/tests.py:596, clients/tests.py:640",
    sourceCode: "clients/views.py:777",
  },
];

const caseTranslations = {
  "PAY-001": {
    scenario: "Orden de contado pagada totalmente en efectivo",
    preconditions: "El cliente tiene una orden de contado pendiente con total_amount = 100.00 y sin pagos existentes.",
    steps: step([
      "Abrir la pantalla de pago de la orden.",
      "Usar monto 100.00 y método de pago Efectivo/cash.",
      "Enviar el pago.",
      "Abrir la orden y el historial de pagos del cliente.",
    ]),
    expected: expect([
      "La respuesta o la UI indica éxito.",
      "Existe un Payment completado por 100.00 con método cash.",
      "La orden queda pagada según total_paid y no se genera movimiento de saldo ni deuda.",
    ]),
    postChecks: "Revisar Payment admin/lista, total_paid de la orden e historial de pagos del cliente.",
  },
  "PAY-002": {
    scenario: "Pago dividido usa saldo del cliente más otro método",
    preconditions: "Saldo del cliente = 30.00. Orden de contado con total_amount = 50.00.",
    steps: step([
      "Abrir la pantalla de checkout/crear orden.",
      "Confirmar que el desglose muestra 30.00 de saldo y 20.00 restante.",
      "Elegir efectivo o transferencia para el monto restante.",
      "Completar el pago.",
    ]),
    expected: expect([
      "Se crean dos pagos: balance 30.00 y el método seleccionado 20.00.",
      "El saldo del cliente baja a 0.00.",
      "Existe BalanceTransaction con transaction_type payment por 30.00.",
      "La orden queda en estado COMPLETED.",
    ]),
    postChecks: "El historial del cliente debe mostrar la deducción de saldo y el pago externo.",
  },
  "PAY-003": {
    scenario: "Se rechaza pago dividido cuando la suma no coincide con el total",
    preconditions: "Orden de contado con total_amount = 100.00.",
    steps: step([
      "Enviar un payload de pago dividido o selección en UI cuyos montos sumen 90.00.",
      "Intentar completar la orden.",
    ]),
    expected: expect([
      "El pago se rechaza con mensaje de que la suma de pagos debe ser igual al total de la orden.",
      "No se crean pagos nuevos.",
      "El estado de la orden no cambia a COMPLETED por este envío.",
    ]),
    postChecks: "Comparar el conteo de pagos de la orden antes y después.",
  },
  "PAY-004": {
    scenario: "Pago con saldo insuficiente es rechazado",
    preconditions: "Saldo del cliente = 30.00. Total de la orden o monto de pago = 50.00.",
    steps: step([
      "Intentar pagar 50.00 usando Saldo/balance.",
      "Enviar el pago.",
    ]),
    expected: expect([
      "El pago se rechaza con mensaje de saldo insuficiente.",
      "No se crea Payment completado con método balance.",
      "El saldo del cliente permanece en 30.00.",
    ]),
    postChecks: "Revisar saldo del cliente y lista de BalanceTransaction.",
  },
  "PAY-005": {
    scenario: "Cantidad cobrada mayor al total agrega excedente al saldo del cliente",
    preconditions: "Orden de contado con total_amount = 100.00. Conocer el saldo inicial del cliente.",
    steps: step([
      "Completar checkout con cantidad_cobrada = 120.00.",
      "Usar un método de pago válido para el total de la orden.",
      "Abrir el detalle del cliente después del pago.",
    ]),
    expected: expect([
      "El pago se procesa correctamente.",
      "La orden guarda cantidad_cobrada = 120.00.",
      "El saldo del cliente aumenta en 20.00.",
      "BalanceTransaction tiene transaction_type added_in_order y referencia la orden.",
    ]),
    postChecks: "Verificar que la respuesta muestre balance_added/new_client_balance cuando aplique.",
  },
  "PAY-006": {
    scenario: "Cantidad cobrada menor al total de la orden es rechazada",
    preconditions: "Orden con total_amount = 100.00.",
    steps: step([
      "Intentar checkout con cantidad_cobrada = 99.99.",
      "Enviar el pago.",
    ]),
    expected: expect([
      "El envío es rechazado.",
      "El error indica que la cantidad cobrada no puede ser menor al total de la orden.",
      "No se agrega saldo y no debe registrarse pago exitoso por este envío.",
    ]),
    postChecks: "Comparar pagos y saldo antes/después.",
  },
  "PAY-007": {
    scenario: "Método de pago inválido en liquidación es rechazado",
    preconditions: "Existe una orden y el usuario inició sesión.",
    steps: step([
      "Enviar una solicitud de pago con un método fuera del conjunto permitido.",
      "Observar la respuesta.",
    ]),
    expected: expect([
      "El pago se rechaza con 'Método de pago inválido para este flujo'.",
      "No se persiste ningún Payment.",
    ]),
    postChecks: "Revisar el conteo de pagos de la orden.",
  },
  "PAY-008": {
    scenario: "Las notas de checkout se guardan en la orden",
    preconditions: "Existe una orden pendiente.",
    steps: step([
      "Capturar una nota durante checkout/pago.",
      "Completar o enviar la solicitud de pago.",
      "Reabrir la orden.",
    ]),
    expected: expect([
      "Las notas de la orden se guardan sin espacios sobrantes.",
      "Las notas en blanco se guardan como vacío/null.",
    ]),
    postChecks: "Revisar el campo en detalle o admin de la orden.",
  },
  "PAY-009": {
    scenario: "El marcador pending_credit completado no cuenta como dinero pagado",
    preconditions: "La orden a crédito solo tiene un Payment pending_credit cambiado a completado y no tiene pago cash/balance.",
    steps: step([
      "Abrir la orden o los totales de factura/pago.",
      "Comparar total_paid contra total_amount.",
    ]),
    expected: expect([
      "El total_paid de la orden es 0.00 para el marcador pending_credit.",
      "La orden sigue apareciendo como no pagada hasta que exista un pago completado distinto de pending_credit.",
    ]),
    postChecks: "Revisar filtros de órdenes no pagadas y total_payments de factura.",
  },
  "BAL-001": {
    scenario: "Depósito manual de saldo actualiza saldo y auditoría",
    preconditions: "Existe un cliente activo. Usuario QA con sesión iniciada.",
    steps: step([
      "Abrir Agregar/Gestionar saldo del cliente.",
      "Seleccionar tipo de transacción Depósito.",
      "Capturar monto 200.00 y notas detalladas de al menos 10 caracteres.",
      "Enviar y abrir el historial de pagos del cliente.",
    ]),
    expected: expect([
      "El saldo del cliente aumenta en 200.00.",
      "Se crea BalanceTransaction con saldos antes/después, created_by y notas.",
      "El mensaje de éxito muestra el saldo actualizado.",
    ]),
    postChecks: "Verificar en admin/historial de BalanceTransaction.",
  },
  "BAL-002": {
    scenario: "Depósito manual exige monto positivo y notas significativas",
    preconditions: "Existe un cliente activo.",
    steps: step([
      "Abrir Agregar saldo.",
      "Intentar monto 0.00 o notas menores a 10 caracteres.",
      "Enviar.",
    ]),
    expected: expect([
      "La validación del formulario bloquea el envío.",
      "No se crea BalanceTransaction.",
      "El saldo del cliente no cambia.",
    ]),
    postChecks: "Confirmar mensajes de validación y ausencia de nueva transacción.",
  },
  "DEBT-001": {
    scenario: "Pago manual de deuda reduce current_debt",
    preconditions: "Cliente con current_debt = 300.00 y credit_limit configurado.",
    steps: step([
      "Abrir Gestionar crédito/pay-credit del cliente.",
      "Seleccionar Pago de deuda.",
      "Capturar monto 100.00, descripción y notas detalladas.",
      "Enviar y abrir el detalle del cliente.",
    ]),
    expected: expect([
      "El current_debt del cliente baja a 200.00.",
      "Se crea CreditTransaction transaction_type payment con debt_before 300.00 y debt_after 200.00.",
      "El crédito disponible aumenta en 100.00.",
    ]),
    postChecks: "Verificar CreditTransaction y totales del reporte global de crédito.",
  },
  "DEBT-002": {
    scenario: "Pagar deuda con saldo actualiza ambos libros",
    preconditions: "Cliente con balance = 150.00 y current_debt = 200.00.",
    steps: step([
      "Abrir Gestionar crédito/pay-credit.",
      "Seleccionar Pago con Saldo.",
      "Capturar monto 100.00 con descripción y notas válidas.",
      "Enviar.",
    ]),
    expected: expect([
      "El saldo del cliente baja a 50.00.",
      "El current_debt baja a 100.00.",
      "Se crea BalanceTransaction transaction_type payment.",
      "Se crea CreditTransaction transaction_type payment_from_balance.",
    ]),
    postChecks: "Revisar ambas secciones de historial en el detalle del cliente.",
  },
  "DEBT-003": {
    scenario: "Pago de deuda con saldo rechaza saldo insuficiente",
    preconditions: "Cliente con balance = 50.00 y current_debt = 200.00.",
    steps: step([
      "Abrir Gestionar crédito/pay-credit.",
      "Seleccionar Pago con Saldo.",
      "Capturar monto 100.00.",
      "Enviar.",
    ]),
    expected: expect([
      "Formulario o servicio bloquea el envío con Saldo insuficiente.",
      "El saldo y la deuda del cliente no cambian.",
      "No se crean transacciones emparejadas.",
    ]),
    postChecks: "Revisar conteos de BalanceTransaction y CreditTransaction.",
  },
  "DEBT-004": {
    scenario: "Pago de deuda no puede exceder la deuda actual",
    preconditions: "Cliente con current_debt = 80.00.",
    steps: step([
      "Abrir Gestionar crédito/pay-credit.",
      "Seleccionar Pago de deuda o Condonación de deuda.",
      "Capturar monto 100.00 y enviar.",
    ]),
    expected: expect([
      "La validación bloquea el envío porque el monto excede la deuda actual.",
      "La deuda permanece en 80.00.",
    ]),
    postChecks: "Confirmar error a nivel de campo monto.",
  },
  "DEBT-005": {
    scenario: "Cambio de límite de crédito crea transacción de auditoría",
    preconditions: "Cliente con credit_limit = 500.00 y current_debt = 100.00.",
    steps: step([
      "Abrir Gestionar crédito/pay-credit.",
      "Seleccionar Cambio de límite de crédito.",
      "Capturar nuevo límite 800.00 y notas válidas.",
      "Enviar.",
    ]),
    expected: expect([
      "El credit_limit del cliente cambia a 800.00.",
      "Se crea CreditTransaction transaction_type limit_change.",
      "CreditTransaction registra credit_limit_before 500.00 y credit_limit_after 800.00.",
    ]),
    postChecks: "Revisar panel de crédito del cliente y crédito disponible en el reporte.",
  },
  "CRED-001": {
    scenario: "Registrar orden a crédito sin saldo",
    preconditions: "Cliente con balance = 0.00, credit_limit = 500.00, current_debt = 0.00, can_pay_with_credit = true. Orden tipo credito, total 100.00.",
    steps: step([
      "Abrir checkout de la orden.",
      "Seleccionar tipo de orden credito.",
      "Finalizar la orden sin elegir método de pago en efectivo.",
      "Abrir detalle del cliente y pagos de la orden.",
    ]),
    expected: expect([
      "La orden queda en estado COMPLETED.",
      "Existe marcador Payment con method pending_credit, status pending, amount 100.00.",
      "El current_debt del cliente aumenta a 100.00.",
      "Existe CreditTransaction purchase referenciando la orden/pago.",
    ]),
    postChecks: "Confirmar que el crédito disponible baja a 400.00.",
  },
  "CRED-002": {
    scenario: "Orden a crédito usa primero el saldo y acredita solo el restante",
    preconditions: "Cliente con balance = 30.00, credit_limit = 100.00, current_debt = 0.00. Orden a crédito total = 50.00.",
    steps: step([
      "Crear una orden a crédito por 50.00.",
      "Finalizar/registrar la orden a crédito.",
      "Abrir pagos y libros.",
    ]),
    expected: expect([
      "Se crea pago balance de 30.00 y queda completado.",
      "Se crea marcador pending_credit por 20.00.",
      "El saldo del cliente queda en 0.00.",
      "El current_debt del cliente queda en 20.00.",
    ]),
    postChecks: "Revisar referencias en transacciones de saldo y crédito.",
  },
  "CRED-003": {
    scenario: "Orden a crédito cubierta totalmente con saldo no crea deuda",
    preconditions: "Cliente con balance = 150.00 y orden a crédito total = 100.00.",
    steps: step([
      "Crear y finalizar una orden tipo credito.",
      "Abrir pagos de la orden y detalle del cliente.",
    ]),
    expected: expect([
      "La orden se completa solo con pago balance.",
      "No queda marcador pending_credit pendiente.",
      "El current_debt del cliente no cambia.",
      "La respuesta/mensaje indica que la orden fue pagada completamente con saldo disponible.",
    ]),
    postChecks: "Confirmar que no exista CreditTransaction purchase para esta orden.",
  },
  "CRED-004": {
    scenario: "Paro de emergencia de crédito bloquea nueva venta a crédito",
    preconditions: "Cliente con balance = 30.00, credit_limit = 200.00, current_debt = 0.00, can_pay_with_credit = false. Orden a crédito total = 100.00.",
    steps: step([
      "Crear una orden a crédito por 100.00.",
      "Intentar finalizar/registrar como credito.",
    ]),
    expected: expect([
      "La solicitud se rechaza con Cliente no puede pagar con credito.",
      "El saldo del cliente permanece en 30.00.",
      "El current_debt permanece en 0.00.",
      "No se crea Payment ni CreditTransaction.",
    ]),
    postChecks: "Debe bloquear aunque el límite numérico de crédito esté disponible.",
  },
  "CRED-005": {
    scenario: "Venta a crédito no puede exceder el límite duro después de aplicar saldo",
    preconditions: "Cliente con balance = 10.00, credit_limit = 100.00, current_debt = 80.00. Orden a crédito total = 50.00.",
    steps: step([
      "Intentar registrar la orden como credito.",
      "Observar error y estado financiero.",
    ]),
    expected: expect([
      "La solicitud se rechaza porque la venta excede el límite de crédito.",
      "El saldo permanece en 10.00 y current_debt en 80.00.",
      "No se crean marcadores de pago.",
    ]),
    postChecks: "Revisar el crédito disponible mostrado al usuario.",
  },
  "CRED-006": {
    scenario: "Crédito vencido se reporta pero no bloquea nueva venta si hay límite",
    preconditions: "Cliente con compra a crédito vencida por 100.00, credit_limit = 500.00, current_debt = 100.00, can_pay_with_credit = true.",
    steps: step([
      "Confirmar que detalle/reporte del cliente muestra crédito vencido.",
      "Crear una nueva orden a crédito por 50.00.",
      "Registrarla como credito.",
    ]),
    expected: expect([
      "La nueva orden a crédito se procesa correctamente.",
      "El current_debt del cliente queda en 150.00.",
      "Existe nuevo marcador pending_credit por 50.00.",
      "El vencimiento sigue visible para la orden anterior.",
    ]),
    postChecks: "Revisar sección de vencidos en detalle del cliente y reporte global de crédito.",
  },
  "CRED-007": {
    scenario: "Registro de orden a crédito es idempotente si ya existe marcador pendiente",
    preconditions: "La orden a crédito ya tiene un marcador Payment pending_credit.",
    steps: step([
      "Enviar/registrar nuevamente la misma orden a crédito.",
      "Revisar pagos y deuda.",
    ]),
    expected: expect([
      "La respuesta indica que la orden ya tiene un registro pendiente de liquidación.",
      "No se crea un pending_credit duplicado.",
      "La deuda no aumenta por segunda vez.",
    ]),
    postChecks: "Comparar conteos de Payment y CreditTransaction antes y después.",
  },
  "CRED-008": {
    scenario: "Liquidar orden con crédito pendiente usando monto exacto",
    preconditions: "Orden a crédito con pending_credit amount 1000.00. Cliente current_debt = 1000.00.",
    steps: step([
      "Abrir la pantalla de pago de la orden a crédito.",
      "Enviar monto 1000.00 con efectivo o transferencia.",
      "Abrir detalle del cliente y pagos de la orden.",
    ]),
    expected: expect([
      "Se crea un pago de liquidación completado.",
      "El current_debt del cliente queda en 0.00.",
      "El crédito disponible se restaura.",
      "El marcador pending_credit cambia a status completed.",
      "CreditTransaction payment referencia la orden y el pago de liquidación.",
    ]),
    postChecks: "La orden debe aparecer pagada porque un pago completado distinto de pending_credit la cubre.",
  },
  "CRED-009": {
    scenario: "Liquidación de crédito pendiente con monto incorrecto es rechazada",
    preconditions: "Orden a crédito con pending_credit amount = 1000.00.",
    steps: step([
      "Abrir pantalla de pago de la orden a crédito.",
      "Enviar monto 900.00.",
    ]),
    expected: expect([
      "El pago se rechaza con mensaje de que debe cubrir el saldo pendiente.",
      "No se crea nuevo pago cash/bank.",
      "pending_credit permanece pending.",
      "La deuda no cambia.",
    ]),
    postChecks: "Verificar conteo de pagos de la orden y deuda del cliente.",
  },
  "CRED-010": {
    scenario: "Pago de liquidación existente y coincidente se reconcilia sin duplicar",
    preconditions: "Orden a crédito con pending_credit 1000.00 y un pago cash completado de 1000.00 que aún no redujo deuda.",
    steps: step([
      "Ejecutar/enviar el flujo de liquidación por 1000.00.",
      "Abrir pagos de la orden.",
    ]),
    expected: expect([
      "Se reutiliza el pago existente.",
      "No se crea pago cash duplicado.",
      "La deuda baja a 0.00.",
      "El marcador pending_credit queda completado.",
    ]),
    postChecks: "Revisar que solo exista un pago cash para la orden.",
  },
  "CRED-011": {
    scenario: "Pago de liquidación existente con monto distinto requiere revisión manual",
    preconditions: "Orden a crédito con pending_credit = 1000.00 y pago cash completado existente = 900.00.",
    steps: step([
      "Intentar liquidar la orden a crédito.",
      "Observar respuesta/error.",
    ]),
    expected: expect([
      "El flujo levanta/devuelve error de revisión manual.",
      "La deuda del cliente no cambia.",
      "No se crea pago adicional.",
    ]),
    postChecks: "Escalar a ingeniería u operaciones financieras con IDs de orden/pago.",
  },
  "CRED-012": {
    scenario: "Migración legacy de crédito en dry-run y apply",
    preconditions: "Una orden legacy tiene type contado y un Payment completado con method credit.",
    steps: step([
      "Ejecutar migrate_legacy_credit_orders sin --apply en un ambiente QA seguro.",
      "Confirmar que no cambian registros.",
      "Ejecutar de nuevo con --apply.",
      "Inspeccionar orden y pago.",
    ]),
    expected: expect([
      "Dry run reporta que no escribe cambios.",
      "--apply cambia order.type a credito.",
      "El pago legacy cambia a method pending_credit y status pending.",
    ]),
    postChecks: "Ejecutar solo en una base QA desechable.",
  },
  "CFG-001": {
    scenario: "La semántica del checkbox de paro de emergencia de crédito se invierte correctamente",
    preconditions: "Cliente con can_pay_with_credit = true y credit_limit = 500.00.",
    steps: step([
      "Abrir editar cliente > pestaña crédito.",
      "Marcar el campo Cliente no puede pagar con crédito.",
      "Guardar.",
      "Abrir el cliente otra vez.",
    ]),
    expected: expect([
      "Cuando el checkbox está marcado, can_pay_with_credit se guarda como false.",
      "Cuando el checkbox está desmarcado, can_pay_with_credit se guarda como true.",
      "Los intentos de venta a crédito respetan el valor guardado.",
    ]),
    postChecks: "Ejecutar CRED-004 después de habilitar el paro de emergencia.",
  },
  "CFG-002": {
    scenario: "Términos de crédito invoice_due requieren facturación recurrente",
    preconditions: "Existe cliente corporativo con requires_billing false.",
    steps: step([
      "Abrir configuración de crédito.",
      "Seleccionar Vencimiento posterior a factura/invoice_due.",
      "Intentar guardar sin habilitar facturación recurrente.",
      "Después habilitar facturación recurrente y guardar invoice_due.",
      "Intentar deshabilitar facturación recurrente mientras invoice_due sigue configurado.",
    ]),
    expected: expect([
      "invoice_due no se puede guardar a menos que requires_billing sea true.",
      "La facturación recurrente no se puede deshabilitar mientras los términos invoice_due estén activos.",
    ]),
    postChecks: "Verificar que el mensaje de validación mencione el requisito de facturación.",
  },
  "CFG-003": {
    scenario: "Nueva sucursal copia política de crédito corporativa pero no saldos de libros",
    preconditions: "Cliente corporativo con credit_limit 750.00, current_debt 320.00, balance 125.00, can_pay_with_credit false y cutoff_day 15.",
    steps: step([
      "Crear una sucursal bajo ese corporativo.",
      "Abrir detalle/editar sucursal > pestaña crédito.",
    ]),
    expected: expect([
      "La sucursal tiene credit_limit 750.00.",
      "La sucursal tiene can_pay_with_credit false.",
      "La sucursal tiene current_debt 0.00 y balance 0.00.",
      "La configuración de crédito copia término de pago, día de corte y máximo de días de pago.",
    ]),
    postChecks: "Confirmar que credit_override_enabled de la sucursal inicia en false.",
  },
  "CFG-004": {
    scenario: "Sucursal sin override de crédito tiene política de crédito de solo lectura",
    preconditions: "La sucursal pertenece a un corporativo y credit_override_enabled es false.",
    steps: step([
      "Abrir editar sucursal > pestaña crédito.",
      "Intentar cambiar credit_limit desde UI o endpoint PATCH.",
    ]),
    expected: expect([
      "La UI muestra configuración de crédito de solo lectura y apunta a la administración corporativa.",
      "La actualización PATCH/API se rechaza con 400.",
      "credit_limit y can_pay_with_credit de la sucursal permanecen sin cambios.",
    ]),
    postChecks: "Usar solo una sucursal con override deshabilitado.",
  },
  "CFG-005": {
    scenario: "Sucursal con override de crédito puede editar su política",
    preconditions: "Sucursal con credit_override_enabled true.",
    steps: step([
      "Abrir editar sucursal > pestaña crédito.",
      "Cambiar credit_limit a 500.00 y guardar.",
      "Opcionalmente hacer PATCH de credit_limit/can_pay_with_credit.",
    ]),
    expected: expect([
      "La UI guarda la política de crédito específica de la sucursal.",
      "PATCH/API puede actualizar campos de crédito.",
      "La política corporativa no se modifica por el cambio en sucursal.",
    ]),
    postChecks: "Comparar valores de sucursal y corporativo.",
  },
  "CFG-006": {
    scenario: "Fechas de vencimiento con corte mensual manejan día de corte y fin de mes",
    preconditions: "Configuración de crédito del cliente con payment_term_type monthly_cutoff.",
    steps: step([
      "Configurar cutoff_day en 20 y crear venta a crédito con fecha 2026-06-21.",
      "Revisar fecha de vencimiento.",
      "Crear otra venta con fecha 2026-06-20.",
      "Configurar cutoff_day last_day o 30 en febrero y revisar vencimiento.",
    ]),
    expected: expect([
      "La venta después del corte vence el 2026-07-20.",
      "La venta en el día de corte vence el 2026-06-20.",
      "last_day usa el último día real del mes.",
      "Un corte numérico mayor al fin de mes se ajusta al último día real.",
    ]),
    postChecks: "El detalle del cliente debe reflejar la fecha de vencimiento más cercana cuando haya crédito abierto.",
  },
  "CFG-007": {
    scenario: "Crédito invoice_due espera emisión de factura y luego suma días máximos",
    preconditions: "Cliente usa invoice_due con max_payment_days = 30.",
    steps: step([
      "Crear una orden a crédito sin factura.",
      "Revisar fecha de vencimiento en reporte/detalle de crédito del cliente.",
      "Crear o ligar factura con emitted_at 2026-06-10.",
      "Revisar nuevamente la fecha de vencimiento.",
    ]),
    expected: expect([
      "La orden sin factura no tiene fecha de vencimiento y no está vencida.",
      "Después de emitir factura, la fecha de vencimiento es 2026-07-10.",
    ]),
    postChecks: "Usar la página detallada del reporte de crédito del cliente.",
  },
  "INV-001": {
    scenario: "Lista de órdenes facturables incluye solo órdenes completadas, sin factura y del mismo cliente",
    preconditions: "Cliente A tiene órdenes completadas sin factura, órdenes pendientes y una orden ya facturada. Cliente B tiene órdenes completadas.",
    steps: step([
      "Abrir flujo de crear/editar factura para Cliente A.",
      "Abrir dropdown de órdenes o endpoint AJAX de órdenes facturables.",
    ]),
    expected: expect([
      "Aparecen las órdenes completadas sin factura de Cliente A.",
      "No aparecen órdenes de Cliente B.",
      "No aparecen órdenes pendientes.",
      "No aparecen órdenes ligadas a cualquier factura.",
    ]),
    postChecks: "Revisar respuesta del endpoint de órdenes facturables si hace falta.",
  },
  "INV-002": {
    scenario: "Editar liga existente de factura conserva la orden actualmente ligada",
    preconditions: "La factura tiene un InvoiceOrderLink existente a una orden que normalmente sería excluida.",
    steps: step([
      "Abrir pantalla de edición de factura.",
      "Editar la fila de la orden ligada existente.",
      "Revisar opciones del dropdown.",
    ]),
    expected: expect([
      "La orden actualmente ligada sigue seleccionable durante la edición.",
      "Otras órdenes ya ligadas permanecen excluidas.",
    ]),
    postChecks: "Esto protege ediciones admin para no perder la selección actual.",
  },
  "INV-003": {
    scenario: "Tope de monto en factura manual bloquea órdenes ligadas que exceden el monto facturado",
    preconditions: "Factura manual con auto_amount false, amount 100.00. Orden ligada existente 80.00. Nueva orden 30.00.",
    steps: step([
      "Abrir pantalla de edición de factura manual.",
      "Intentar ligar la nueva orden de 30.00.",
    ]),
    expected: expect([
      "El formulario bloquea la liga porque el total ligado sería 110.00.",
      "No se crea InvoiceOrderLink para la nueva orden.",
      "El error explica que la suma excede el monto de la factura.",
    ]),
    postChecks: "Revisar que la tabla de órdenes ligadas no cambie.",
  },
  "INV-004": {
    scenario: "Tope de factura manual permite límite exacto",
    preconditions: "Factura manual amount 100.00. Orden ligada existente 80.00. Nueva orden completada 20.00.",
    steps: step([
      "Abrir edición de factura.",
      "Ligar la orden de 20.00.",
    ]),
    expected: expect([
      "El formulario guarda correctamente.",
      "El total de órdenes ligadas es igual al monto de la factura 100.00.",
    ]),
    postChecks: "Revisar la suma de órdenes ligadas a la factura.",
  },
  "INV-005": {
    scenario: "Factura con monto automático deriva el monto desde órdenes ligadas",
    preconditions: "Factura automática inicialmente liga orden de 50.00.",
    steps: step([
      "Crear factura desde órdenes completadas o habilitar auto_amount.",
      "Agregar otra orden completada por 25.00.",
      "Guardar edición de factura.",
    ]),
    expected: expect([
      "La factura auto_amount acepta órdenes ligadas aunque el monto previo hubiera sido excedido.",
      "El monto de la factura se sincroniza a 75.00.",
      "Si se quitan todas las ligas, el monto se sincroniza a 0.00.",
    ]),
    postChecks: "Revisar monto de factura después de guardar y después de quitar ligas.",
  },
  "INV-006": {
    scenario: "Crear factura masiva desde órdenes completadas del mismo cliente",
    preconditions: "Usuario admin. Dos órdenes completadas para el mismo cliente corporativo listo para facturar: 50.00 y 30.00.",
    steps: step([
      "Abrir dashboard admin de órdenes.",
      "Seleccionar ambas órdenes completadas.",
      "Elegir acción masiva Crear factura.",
      "Enviar.",
    ]),
    expected: expect([
      "Redirige a pantalla de edición de factura.",
      "Se crea factura por 80.00.",
      "La factura tiene dos filas InvoiceOrderLink.",
      "identifier y folio son placeholders BORRADOR para actualización posterior.",
    ]),
    postChecks: "Revisar IDs de órdenes ligadas a la factura.",
  },
  "INV-007": {
    scenario: "Crear factura masiva rechaza órdenes no completadas",
    preconditions: "La selección incluye una orden completada y una pendiente.",
    steps: step([
      "Abrir dashboard admin de órdenes.",
      "Seleccionar órdenes con estados mixtos.",
      "Elegir Crear factura y enviar.",
    ]),
    expected: expect([
      "No se crea factura.",
      "El mensaje indica que solo órdenes completadas pueden facturarse.",
      "El ID de la orden pendiente aparece en el contexto del error.",
    ]),
    postChecks: "Revisar conteo de facturas para el cliente.",
  },
  "INV-008": {
    scenario: "Crear factura masiva rechaza órdenes de corporativos distintos",
    preconditions: "Las órdenes completadas seleccionadas pertenecen a propietarios corporativos distintos.",
    steps: step([
      "Seleccionar órdenes completadas de distintos clientes corporativos.",
      "Ejecutar Crear factura.",
    ]),
    expected: expect([
      "No se crea factura.",
      "El error indica que todas las órdenes seleccionadas deben pertenecer al mismo cliente corporativo.",
    ]),
    postChecks: "Incluir combinaciones sucursal/corporativo en esta prueba.",
  },
  "INV-009": {
    scenario: "Generación de factura rechaza datos fiscales o dirección fiscal faltantes",
    preconditions: "Cliente con órdenes completadas pero sin RFC/razon_social o sin dirección fiscal activa.",
    steps: step([
      "Ejecutar Crear factura desde admin de órdenes.",
      "Repetir con RFC/razon_social faltante.",
      "Repetir con dirección fiscal activa faltante.",
    ]),
    expected: expect([
      "No se crea factura.",
      "El error identifica RFC/Razón social o dirección fiscal faltante.",
      "Para sucursales, se nombra al corporativo cuando faltan datos corporativos.",
    ]),
    postChecks: "Revisar que no se creen filas parciales de factura/liga.",
  },
  "INV-010": {
    scenario: "Factura de sucursal valida datos fiscales corporativos, no datos propios de sucursal",
    preconditions: "La sucursal tiene datos/dirección fiscal propios, pero su corporativo no tiene RFC o dirección de facturación.",
    steps: step([
      "Seleccionar una orden completada de sucursal.",
      "Ejecutar Crear factura.",
    ]),
    expected: expect([
      "La creación de factura se rechaza.",
      "El error referencia al cliente corporativo como propietario fiscal requerido.",
      "Los datos fiscales de la sucursal no evitan la validación corporativa.",
    ]),
    postChecks: "Revisar configuración de sucursal y corporativo antes de la prueba.",
  },
  "INV-011": {
    scenario: "Snapshot de balance de factura separa capacidad disponible de saldo no pagado",
    preconditions: "Factura amount 1000.00 ligada a órdenes por 800.00. Pagos incluyen cash 600.00 y pending_credit 50.00.",
    steps: step([
      "Abrir lista/dashboard de facturas o vista/servicio de snapshot si existe en UI.",
      "Comparar totales de órdenes ligadas y pagos completados no crediticios.",
    ]),
    expected: expect([
      "La capacidad disponible es 200.00 porque el monto de factura excede los totales ligados.",
      "El saldo no pagado es 400.00 porque pending_credit se excluye del total pagado.",
      "Una factura completamente usada/pagada no cuenta en ninguno de los dos grupos.",
    ]),
    postChecks: "Usar columnas de monto, total de pagos y pendiente en la lista de facturas.",
  },
  "INV-012": {
    scenario: "Pantallas admin de crear y editar factura guardan campos y ligas",
    preconditions: "Usuario staff/admin y cliente listo para facturar.",
    steps: step([
      "Abrir Administrador > Facturas > Nueva Factura.",
      "Crear factura con cliente, serie, folio y amount 150.00.",
      "Abrir edición y ligar una orden completada.",
    ]),
    expected: expect([
      "Crear redirige a la página de edición.",
      "La factura existe con identifier/folio/amount capturados.",
      "La orden ligada aparece en la tabla de ventas ligadas de la factura.",
    ]),
    postChecks: "El campo de archivo se puede probar aparte si QA tiene PDF/XML de muestra.",
  },
  "CAN-001": {
    scenario: "Cancelar orden pendiente la marca como cancelada sin borrar productos",
    preconditions: "Existe una orden pendiente con al menos un producto.",
    steps: step([
      "Abrir pantalla de la orden.",
      "Hacer clic en cancelar orden y confirmar.",
      "Abrir admin/detalle de la orden.",
    ]),
    expected: expect([
      "El estado de la orden cambia a CANCELLED.",
      "Las filas OrderProduct siguen presentes para auditoría/historial.",
      "No se marca bandera de revisión de cancelación.",
    ]),
    postChecks: "Revisar filtros de lista de órdenes activas/canceladas.",
  },
  "CAN-002": {
    scenario: "Cancelar orden completada pagada en efectivo revierte estado del pago externo",
    preconditions: "Orden completada con pago cash completado.",
    steps: step([
      "Cancelar la orden completada.",
      "Abrir pagos de la orden.",
    ]),
    expected: expect([
      "El estado de la orden cambia a CANCELLED.",
      "El pago cash cambia a status reversed.",
      "Balance y deuda del cliente no cambian para pago solo en efectivo.",
    ]),
    postChecks: "Revisar que reportes no cuenten pagos revertidos.",
  },
  "CAN-003": {
    scenario: "Cancelar orden pagada con saldo restaura el saldo",
    preconditions: "Orden completada con pago balance 40.00 y saldo del cliente reducido de 100.00 a 60.00.",
    steps: step([
      "Cancelar la orden completada.",
      "Abrir historial del detalle del cliente.",
    ]),
    expected: expect([
      "El saldo del cliente vuelve a 100.00.",
      "El pago original con saldo queda marcado como reversed.",
      "Existe BalanceTransaction transaction_type payment_reversal y referencia el pago.",
    ]),
    postChecks: "Confirmar que la orden está en CANCELLED.",
  },
  "CAN-004": {
    scenario: "Cancelar orden a crédito abierta revierte compra a crédito",
    preconditions: "Orden credito completada con marcador pending_credit pendiente y CreditTransaction purchase 50.00. Cliente current_debt = 50.00.",
    steps: step([
      "Cancelar la orden a crédito.",
      "Abrir historial de crédito del cliente y pagos de la orden.",
    ]),
    expected: expect([
      "current_debt del cliente queda en 0.00.",
      "El pago pending_credit cambia a status reversed.",
      "Existe CreditTransaction purchase_reversal para la orden.",
    ]),
    postChecks: "Revisar que el crédito disponible se restaure.",
  },
  "CAN-005": {
    scenario: "Cancelar orden a crédito liquidada revierte pago de liquidación y compra",
    preconditions: "Orden a crédito con pending_credit completed, liquidación cash completed, transacciones purchase y payment. La deuda actual del cliente es 0.00.",
    steps: step([
      "Cancelar la orden a crédito liquidada.",
      "Abrir pagos de la orden y transacciones de crédito del cliente.",
    ]),
    expected: expect([
      "pending_credit y pago cash de liquidación cambian a reversed.",
      "Una transacción payment_reversal restaura la deuda liquidada.",
      "Una transacción purchase_reversal revierte la compra original a crédito.",
      "current_debt final del cliente permanece en 0.00.",
    ]),
    postChecks: "La orden queda CANCELLED y el reporte de crédito ya no infla crédito abierto.",
  },
  "CAN-006": {
    scenario: "Cancelar orden cuyo saldo agregado fue gastado requiere revisión",
    preconditions: "La orden con cantidad_cobrada agregó 50.00 al saldo del cliente, pero el balance actual ya es 0.00.",
    steps: step([
      "Intentar cancelar la orden completada.",
      "Abrir lista/admin de órdenes.",
    ]),
    expected: expect([
      "La cancelación falla con review_required true.",
      "La orden permanece COMPLETED.",
      "cancellation_review_required queda true y la razón menciona saldo.",
      "Aparece badge de revisión en lista/admin de órdenes.",
    ]),
    postChecks: "Finanzas/admin debe resolver manualmente antes de reintentar.",
  },
  "CAN-007": {
    scenario: "Cancelar orden ligada a factura requiere revisión",
    preconditions: "Orden completada ligada a una factura.",
    steps: step([
      "Intentar cancelar la orden.",
      "Abrir lista de órdenes y facturas en detalle del cliente.",
    ]),
    expected: expect([
      "La cancelación falla con review_required true.",
      "La orden permanece COMPLETED.",
      "La razón de revisión menciona factura.",
      "Aparece badge de revisión en listas de usuario/admin.",
    ]),
    postChecks: "La liga de factura debe revisarse antes de proceder con cancelación.",
  },
  "CAN-008": {
    scenario: "Reintento exitoso de cancelación limpia metadatos de revisión",
    preconditions: "Orden con cancellation_review_required true por un intento bloqueado previo y el bloqueo ya fue resuelto.",
    steps: step([
      "Reintentar cancelación después de resolver el problema.",
      "Abrir registro de la orden.",
    ]),
    expected: expect([
      "La cancelación se completa.",
      "El estado de la orden cambia a CANCELLED.",
      "cancellation_review_required, reason, requested_at y requested_by quedan limpios.",
    ]),
    postChecks: "La orden ya no aparece bajo filtro REVIEW_REQUIRED.",
  },
  "REP-001": {
    scenario: "Reporte global de crédito muestra columnas de crédito y ordenamiento correcto",
    preconditions: "Cliente activo Tempano con current_debt 17000.00, credit_limit 20000.00, vencido 9700.00. Cliente activo Vigor con current_debt 8300.00 sin vencido. También existen clientes inactivos y sin crédito.",
    steps: step([
      "Abrir Reportes > Crédito global.",
      "Revisar filas y totales.",
    ]),
    expected: expect([
      "Columnas incluyen Crédito vigente, Línea de crédito autorizada, Disponible y Monto vencido.",
      "Aparecen clientes activos con crédito/deuda.",
      "Clientes inactivos y sin crédito/sin deuda se excluyen.",
      "Las filas se ordenan por monto vencido descendente y luego deuda actual descendente.",
    ]),
    postChecks: "Usar filtro de búsqueda si el dataset es grande.",
  },
  "REP-002": {
    scenario: "Reporte de crédito de cliente separa crédito abierto facturado y no facturado",
    preconditions: "Cliente con dos órdenes a crédito facturadas por 9700.00 y una orden a crédito sin factura por 4500.00. Current debt = 14200.00.",
    steps: step([
      "Abrir detalle de cliente y hacer clic en Reporte de crédito.",
      "Revisar secciones del reporte detallado.",
    ]),
    expected: expect([
      "Total de crédito facturado es 9700.00.",
      "Total de crédito no facturado es 4500.00.",
      "El ítem de factura muestra identifier/folio de la factura.",
      "No aparece advertencia de reconciliación cuando current_debt coincide con crédito abierto total.",
    ]),
    postChecks: "Revisar que exista la liga al reporte desde detalle del cliente.",
  },
  "REP-003": {
    scenario: "Crédito invoice_due no facturado no está vencido hasta emisión de factura",
    preconditions: "Cliente usa invoice_due. Existe orden a crédito antigua sin liga a factura con emmited_at.",
    steps: step([
      "Abrir reporte global de crédito y reporte de crédito del cliente.",
      "Inspeccionar monto vencido y fecha de vencimiento de la orden.",
    ]),
    expected: expect([
      "El monto vencido del reporte global es 0.00 para este cliente/orden.",
      "El reporte de cliente no muestra fecha de vencimiento para la orden sin factura.",
      "La orden sin factura no se marca como vencida.",
    ]),
    postChecks: "Después ligar factura/fecha de emisión y ejecutar CFG-007.",
  },
  "REP-004": {
    scenario: "Órdenes canceladas y pagos revertidos no inflan crédito abierto ni reportes de pagos",
    preconditions: "Cliente con orden a crédito activa 100.00, orden a crédito cancelada 500.00 y pago cash revertido 100.00.",
    steps: step([
      "Abrir reporte de crédito del cliente.",
      "Abrir reportes de órdenes/pagos filtrados por método de pago si aplica.",
    ]),
    expected: expect([
      "El total de crédito abierto permanece en 100.00.",
      "El monto vencido solo incluye orden activa sin pagar.",
      "El pago revertido se ignora en reportes filtrados por método de pago.",
    ]),
    postChecks: "Revisar que la orden cancelada se excluya por defecto de reportes.",
  },
  "REP-005": {
    scenario: "Export CSV del reporte global de crédito contiene columnas requeridas",
    preconditions: "El reporte de crédito tiene al menos una fila de cliente.",
    steps: step([
      "Abrir reporte global de crédito.",
      "Hacer clic en exportar CSV.",
      "Abrir el CSV descargado.",
    ]),
    expected: expect([
      "Headers CSV: Cliente, Crédito vigente, Línea de crédito autorizada, Disponible, Monto vencido.",
      "Los valores de moneda se exportan como decimales crudos con dos decimales.",
      "Los filtros de búsqueda se preservan en la liga de exportación.",
    ]),
    postChecks: "Validar con cliente llamado Tempano si se usa dataset de prueba.",
  },
  "REP-006": {
    scenario: "Modo créditos de lista de clientes filtra clientes con deuda",
    preconditions: "Al menos un cliente tiene current_debt > 0 y al menos un cliente activo tiene deuda cero.",
    steps: step([
      "Abrir lista de clientes con mode=credits.",
      "Usar búsqueda y paginación.",
    ]),
    expected: expect([
      "Solo aparecen clientes con current_debt mayor a 0.",
      "Búsqueda y paginación preservan mode=credits.",
      "Título/subtítulo indican contexto de cobranza de crédito.",
    ]),
    postChecks: "Usar detalle del cliente para clientes seleccionados con deuda.",
  },
};

const setupRows = [
  ["SET-001", "Usuario", "Crear o usar una cuenta QA staff/superuser.", "Todos los casos admin y reportes", "Usar la misma cuenta para que created_by sea fácil de auditar."],
  ["SET-002", "Producto", "Crear producto QA Garrafón con precio conocido, por ejemplo 25.00.", "Casos de creación de órdenes", "Cualquier producto sirve si los totales de orden coinciden con los montos del escenario."],
  ["SET-003", "Cliente contado", "Crear QA Contado con balance 0.00, credit_limit 0.00, current_debt 0.00.", "PAY-001, PAY-003, PAY-006", "Usar para flujos ordinarios de pago."],
  ["SET-004", "Cliente con saldo", "Crear QA Balance con balance 100.00 y current_debt 0.00.", "PAY-002, PAY-004, BAL-001, BAL-002, CAN-003", "Registrar saldo inicial antes de cada prueba."],
  ["SET-005", "Cliente crédito OK", "Crear QA Crédito OK con balance 0.00, credit_limit 500.00, current_debt 0.00, can_pay_with_credit true, monthly_cutoff last_day.", "CRED-001, CRED-006, CRED-008, REP-001", "Usar montos exactos de deuda/límite según cada escenario."],
  ["SET-006", "Cliente crédito mixto", "Crear QA Crédito Mixto con balance 30.00, credit_limit 100.00, current_debt 0.00, can_pay_with_credit true.", "CRED-002, CRED-005", "Reiniciar saldo/deuda entre ejecuciones."],
  ["SET-007", "Cliente crédito bloqueado", "Crear QA Crédito Bloqueado con balance 30.00, credit_limit 200.00, current_debt 0.00, can_pay_with_credit false.", "CRED-004, CFG-001", "La etiqueta del checkbox está invertida: marcado significa bloquear crédito."],
  ["SET-008", "Corporativo listo para factura", "Crear QA Factura Corp con type corporate, InvoiceData RFC/razon_social y una dirección fiscal/facturación activa.", "INV-001 a INV-012", "Las pruebas usan RFC placeholder tipo AAA010101AAA."],
  ["SET-009", "Par sucursal/corporativo", "Crear clientes corporativo y sucursal para herencia y validación de factura; variar completitud fiscal corporativa.", "CFG-003, CFG-004, CFG-005, INV-010", "Los datos fiscales de sucursal no deben saltarse la validación fiscal corporativa."],
  ["SET-010", "Dataset reporte crédito", "Crear clientes estilo Tempano/Vigor con compras a crédito fechadas 2026-04-01 y 2026-07-01.", "REP-001, REP-002, REP-003, REP-004", "Usar base QA desechable porque las fechas son específicas del escenario."],
  ["SET-011", "Términos invoice_due", "Para pruebas invoice_due, configurar requires_billing true y max_payment_days 30.", "CFG-002, CFG-007, REP-003", "Órdenes sin factura no deben tener fecha de vencimiento."],
  ["SET-012", "Limpieza/reinicio", "Después de cada caso con movimiento de dinero, registrar saldos/deudas iniciales y finales, IDs de orden, pago y transacciones.", "Todos los casos financieros", "Esta hoja es para notas de ejecución manual, no para teardown automatizado."],
];

const sourceRows = [
  ["Pagos", "Enrutamiento de solicitud de pago, pago único/múltiple, cantidad_cobrada", "payment/services.py:33, payment/services.py:216, payment/services.py:285, payment/services.py:337", "payment/tests.py:26, payment/tests.py:56, payment/tests.py:76, payment/tests.py:118", "PAY-001 a PAY-009"],
  ["Pagos", "Pantalla de pago de orden, métodos válidos, entrada para liquidar crédito pendiente", "orders/views.py:67, orders/views.py:113", "payment/tests.py:294, orders/tests.py:1511", "PAY-001, CRED-008, CRED-009"],
  ["Balance", "Mutaciones de saldo y filas de auditoría", "clients/services/balance_service.py:59, clients/services/balance_service.py:120, clients/models.py:320", "tests/test_balance_credit_history.py:1, orders/tests.py:554", "BAL-001, BAL-002, CAN-003"],
  ["Deuda", "Pago de deuda, pago desde saldo, cambios de límite de crédito", "clients/services/balance_service.py:261, clients/services/balance_service.py:431, clients/services/balance_service.py:488", "tests/test_balance_credit_history.py:1", "DEBT-001 a DEBT-005"],
  ["Órdenes a crédito", "Ciclo de vida para registrar y liquidar órdenes a crédito", "payment/services.py:403, payment/services.py:423, payment/services.py:501, payment/services.py:108", "payment/tests.py:205, payment/tests.py:316, payment/tests.py:344, payment/tests.py:396", "CRED-001 a CRED-011"],
  ["Config crédito", "Disponibilidad de crédito, paro de emergencia, override/herencia de sucursal", "clients/models.py:195, clients/models.py:199, clients/services/client_service.py:51, clients/views.py:262", "clients/tests_credit_management.py:75, clients/tests_credit_management.py:170, clients/tests_credit_management.py:301", "CFG-001 a CFG-005"],
  ["Términos crédito", "Cálculo de corte mensual y fecha de vencimiento por factura", "clients/services/pending_payment_service.py:27, clients/services/pending_payment_service.py:40", "clients/tests_credit_terms.py:13, clients/tests_credit_terms.py:33, clients/tests_credit_terms.py:46", "CFG-006, CFG-007, REP-003"],
  ["Facturas", "Órdenes facturables, validación de tope, creación y sincronización de factura", "invoice/services.py:265, invoice/services.py:314, invoice/services.py:352, invoice/services.py:476, invoice/services.py:534", "invoice/tests.py:38, invoice/tests.py:130, invoice/tests.py:413, invoice/tests.py:469", "INV-001 a INV-012"],
  ["Facturas", "Vistas admin de factura y acción masiva Crear factura", "invoice/views.py:120, invoice/views.py:142, orders/views.py:253", "invoice/tests.py:523, invoice/tests.py:542, orders/tests.py:1043", "INV-006, INV-012"],
  ["Cancelaciones", "Reversas financieras y lógica review_required", "orders/services.py:237, orders/services.py:267, orders/services.py:281, orders/services.py:302, orders/services.py:329", "orders/tests.py:656, orders/tests.py:693, orders/tests.py:721, orders/tests.py:757, orders/tests.py:819, orders/tests.py:844", "CAN-001 a CAN-008"],
  ["Reportes", "Reportes de crédito global y por cliente", "clients/services/credit_report_service.py:250, clients/services/credit_report_service.py:261, report/views.py:235, report/views.py:262", "clients/tests_credit_report_service.py:73, clients/tests_credit_report_service.py:120, report/tests.py:506, report/tests.py:520", "REP-001 a REP-006"],
  ["Detalle cliente", "Estado de crédito del cliente, vencidos, facturas e historial de pagos", "clients/views.py:576, clients/views.py:608, clients/services/pending_payment_service.py:94", "clients/tests.py:416, clients/tests.py:501, clients/tests_credit_management.py:542", "CRED-006, REP-002, REP-006"],
];

const guideRows = [
  ["Propósito", "Handoff QA manual para escenarios de pagos, facturas, crédito y deuda trazados desde las pruebas unitarias y el código fuente actual."],
  ["Entregable principal", "Importar este XLSX en Google Sheets. Crear una hoja nativa requeriría instalar el plugin Google Drive."],
  ["Orden recomendado", "Ejecutar setup y luego casos P0 primero: PAY, CRED, INV, CAN, REP. Completar P1/P2 después de validar flujos financieros base."],
  ["Ambiente de ejecución", "Usar base de datos o tenant QA desechable. Muchos casos mutan saldos, deudas, pagos, facturas y estado de cancelación."],
  ["Registro de evidencia", "Para cada caso, llenar Estado, Responsable, Fecha probada, Resultado real, Liga defecto y Notas en Casos Manuales."],
  ["Enfoque de auditoría", "Registrar siempre ID de cliente, orden, pago, factura, BalanceTransaction y CreditTransaction cuando existan."],
  ["Trazabilidad", "Usar la pestaña Mapa de Fuentes para mapear cada caso manual contra pruebas automatizadas y código de servicio."],
  ["Terminología", "Saldo = balance prepago. Deuda/current_debt = monto adeudado. Payment pending_credit = marcador de crédito, no dinero pagado."],
];

function colName(index) {
  let name = "";
  let n = index;
  while (n > 0) {
    const rem = (n - 1) % 26;
    name = String.fromCharCode(65 + rem) + name;
    n = Math.floor((n - 1) / 26);
  }
  return name;
}

function a1(row, col) {
  return `${colName(col)}${row}`;
}

function rangeA1(startRow, startCol, rowCount, colCount) {
  return `${a1(startRow, startCol)}:${a1(startRow + rowCount - 1, startCol + colCount - 1)}`;
}

function writeTable(sheet, headers, rows, tableName) {
  const allRows = [headers, ...rows];
  const range = sheet.getRange(rangeA1(1, 1, allRows.length, headers.length));
  range.values = allRows;
  range.format = {
    font: { name: "Calibri", size: 10, color: "#111827" },
    verticalAlignment: "top",
    wrapText: true,
  };
  range.getRow(0).format = {
    fill: "#1F4E78",
    font: { name: "Calibri", size: 10, color: "#FFFFFF", bold: true },
    horizontalAlignment: "center",
    verticalAlignment: "center",
    wrapText: true,
    borders: { preset: "outside", style: "thin", color: "#1F4E78" },
  };
  range.format.borders = {
    insideHorizontal: { style: "thin", color: "#E5E7EB" },
    insideVertical: { style: "thin", color: "#F3F4F6" },
    bottom: { style: "thin", color: "#D1D5DB" },
  };
  sheet.freezePanes.freezeRows(1);
  const table = sheet.tables.add(rangeA1(1, 1, allRows.length, headers.length), true, tableName);
  table.showFilterButton = true;
  return range;
}

function setWidths(sheet, widths, rowCount) {
  widths.forEach((width, index) => {
    sheet.getRangeByIndexes(0, index, rowCount, 1).format.columnWidthPx = width;
  });
}

function styleManualCases(sheet, caseCount) {
  const rowCount = caseCount + 1;
  setWidths(sheet, [90, 110, 70, 250, 280, 360, 360, 260, 180, 210, 210, 105, 120, 115, 260, 180, 260], rowCount);
  sheet.getRange(`A2:Q${rowCount}`).format.rowHeightPx = 118;
  sheet.getRange(`A2:C${rowCount}`).format.horizontalAlignment = "center";
  sheet.getRange(`L2:L${rowCount}`).dataValidation = {
    rule: { type: "list", values: statuses },
  };
  sheet.getRange(`B2:B${rowCount}`).dataValidation = {
    rule: { type: "list", values: areas },
  };
  sheet.getRange(`C2:C${rowCount}`).dataValidation = {
    rule: { type: "list", values: priorities },
  };
  sheet.getRange(`N2:N${rowCount}`).format.numberFormat = "yyyy-mm-dd";
  sheet.getRange(`L2:L${rowCount}`).conditionalFormats.add("containsText", {
    text: "Aprobado",
    format: { fill: "#DCFCE7", font: { color: "#166534", bold: true } },
  });
  sheet.getRange(`L2:L${rowCount}`).conditionalFormats.add("containsText", {
    text: "Fallido",
    format: { fill: "#FEE2E2", font: { color: "#991B1B", bold: true } },
  });
  sheet.getRange(`L2:L${rowCount}`).conditionalFormats.add("containsText", {
    text: "Bloqueado",
    format: { fill: "#FEF3C7", font: { color: "#92400E", bold: true } },
  });
}

function buildOverview(sheet, caseCount) {
  sheet.showGridLines = false;
  sheet.getRange("A1:K22").format.font = { name: "Calibri", size: 10, color: "#111827" };
  sheet.getRange("A1:H1").merge();
  sheet.getRange("A1").values = [["Handoff QA Manual: Pagos, Facturas, Crédito y Deuda"]];
  sheet.getRange("A1:H1").format = {
    fill: "#0F172A",
    font: { name: "Calibri", size: 16, color: "#FFFFFF", bold: true },
    verticalAlignment: "center",
  };
  sheet.getRange("A1:H1").format.rowHeightPx = 34;
  sheet.getRange("A2:H2").merge();
  sheet.getRange("A2").values = [[`Generado el 2026-07-22 desde pruebas unitarias y código de servicios. Total de casos manuales: ${caseCount}.`]];
  sheet.getRange("A2:H2").format = {
    fill: "#E0F2FE",
    font: { name: "Calibri", size: 10, color: "#0F172A" },
  };

  const summaryHeaders = [["Área", "Total", "P0", "P1", "P2", "Sin iniciar", "Aprobado", "Fallido"]];
  sheet.getRange("A4:H4").values = summaryHeaders;
  sheet.getRange("A4:H4").format = {
    fill: "#1F4E78",
    font: { color: "#FFFFFF", bold: true },
    horizontalAlignment: "center",
  };
  const summaryRows = areas.map((area, index) => {
    const row = 5 + index;
    return [
      area,
      `=COUNTIF('Casos Manuales'!$B$2:$B$${caseCount + 1},A${row})`,
      `=COUNTIFS('Casos Manuales'!$B$2:$B$${caseCount + 1},A${row},'Casos Manuales'!$C$2:$C$${caseCount + 1},"P0")`,
      `=COUNTIFS('Casos Manuales'!$B$2:$B$${caseCount + 1},A${row},'Casos Manuales'!$C$2:$C$${caseCount + 1},"P1")`,
      `=COUNTIFS('Casos Manuales'!$B$2:$B$${caseCount + 1},A${row},'Casos Manuales'!$C$2:$C$${caseCount + 1},"P2")`,
      `=COUNTIFS('Casos Manuales'!$B$2:$B$${caseCount + 1},A${row},'Casos Manuales'!$L$2:$L$${caseCount + 1},"Sin iniciar")`,
      `=COUNTIFS('Casos Manuales'!$B$2:$B$${caseCount + 1},A${row},'Casos Manuales'!$L$2:$L$${caseCount + 1},"Aprobado")`,
      `=COUNTIFS('Casos Manuales'!$B$2:$B$${caseCount + 1},A${row},'Casos Manuales'!$L$2:$L$${caseCount + 1},"Fallido")`,
    ];
  });
  sheet.getRange(`A5:H${4 + summaryRows.length}`).formulas = summaryRows.map((row) => [
    row[0],
    ...row.slice(1),
  ]);
  sheet.getRange(`A5:A${4 + summaryRows.length}`).values = areas.map((area) => [area]);
  sheet.getRange(`A4:H${4 + summaryRows.length}`).format.borders = {
    preset: "all",
    style: "thin",
    color: "#D1D5DB",
  };
  sheet.getRange(`B5:H${4 + summaryRows.length}`).format.numberFormat = "0";

  const statusRows = [
    ["Total general", `=COUNTA('Casos Manuales'!$A$2:$A$${caseCount + 1})`],
    ["Conteo P0", `=COUNTIF('Casos Manuales'!$C$2:$C$${caseCount + 1},"P0")`],
    ["Aprobados", `=COUNTIF('Casos Manuales'!$L$2:$L$${caseCount + 1},"Aprobado")`],
    ["Fallidos", `=COUNTIF('Casos Manuales'!$L$2:$L$${caseCount + 1},"Fallido")`],
    ["Bloqueados", `=COUNTIF('Casos Manuales'!$L$2:$L$${caseCount + 1},"Bloqueado")`],
  ];
  sheet.getRange("J4:K4").values = [["Resumen ejecución", "Conteo"]];
  sheet.getRange("J4:K4").format = {
    fill: "#475569",
    font: { color: "#FFFFFF", bold: true },
    horizontalAlignment: "center",
  };
  sheet.getRange("J5:K9").formulas = statusRows;
  sheet.getRange("J5:J9").values = statusRows.map((row) => [row[0]]);
  sheet.getRange("J4:K9").format.borders = {
    preset: "all",
    style: "thin",
    color: "#D1D5DB",
  };
  sheet.getRange("K5:K9").format.numberFormat = "0";
  sheet.getRange("A15:B22").values = [
    ["Guía QA", ""],
    ["1", "Ejecutar primero casos P0. Cubren movimientos de dinero, creación de factura, registro/liquidación de crédito y reversas de cancelación."],
    ["2", "Usar tenant/base QA desechable. Los casos mutan saldos, deudas, facturas, pagos y estados de órdenes."],
    ["3", "Registrar IDs de objetos y valores financieros antes/después en la hoja Casos Manuales."],
    ["4", "Importar este XLSX en Google Sheets si se necesita una hoja compartida nativa."],
    ["5", "Crear una Google Sheet nativa requiere el plugin Google Drive, que no está instalado en esta sesión de Codex."],
    ["6", "Mapa de Fuentes contiene referencias de código y pruebas para auditoría."],
    ["", ""],
  ];
  sheet.getRange("A15:B15").format = {
    fill: "#1F4E78",
    font: { color: "#FFFFFF", bold: true },
  };
  sheet.getRange("A16:B21").format = {
    fill: "#F8FAFC",
    wrapText: true,
    verticalAlignment: "top",
    borders: { preset: "outside", style: "thin", color: "#CBD5E1" },
  };
  sheet.getRange("A16:B21").format.rowHeightPx = 64;
  setWidths(sheet, [130, 320, 80, 80, 80, 115, 80, 80, 30, 180, 90], 22);
}

const workbook = Workbook.create();
const overview = workbook.worksheets.add("Resumen");
const manual = workbook.worksheets.add("Casos Manuales");
const setup = workbook.worksheets.add("Datos de Prueba");
const source = workbook.worksheets.add("Mapa de Fuentes");
const guide = workbook.worksheets.add("Guía de Ejecución");

for (const sheet of [overview, manual, setup, source, guide]) {
  sheet.showGridLines = false;
}

const caseHeaders = [
  "ID Caso",
  "Área",
  "Prioridad",
  "Escenario",
  "Precondiciones / Datos",
  "Pasos manuales",
  "Resultados esperados",
  "Post-checks / Evidencia",
  "Pruebas fuente",
  "Código fuente",
  "Notas QA",
  "Estado",
  "Responsable",
  "Fecha probada",
  "Resultado real",
  "Liga defecto",
  "Notas de ejecución",
];

const missingTranslations = manualCases.filter((item) => !caseTranslations[item.id]);
if (missingTranslations.length > 0) {
  throw new Error(`Faltan traducciones para casos: ${missingTranslations.map((item) => item.id).join(", ")}`);
}

const localizedCases = manualCases.map((item) => ({
  ...item,
  ...caseTranslations[item.id],
  area: areaLabels[item.area] ?? item.area,
}));

const caseRows = localizedCases.map((item) => [
  item.id,
  item.area,
  item.priority,
  item.scenario,
  item.preconditions,
  item.steps,
  item.expected,
  item.postChecks,
  item.sourceTests,
  item.sourceCode,
  "",
  statuses[0],
  "",
  null,
  "",
  "",
  "",
]);

writeTable(manual, caseHeaders, caseRows, "ManualCasesTable");
styleManualCases(manual, localizedCases.length);

writeTable(
  setup,
  ["ID Setup", "Entidad", "Instrucciones de preparación", "Usado por", "Notas"],
  setupRows,
  "DataSetupTable",
);
setWidths(setup, [90, 140, 430, 240, 330], setupRows.length + 1);
setup.getRange(`A2:E${setupRows.length + 1}`).format.rowHeightPx = 70;

writeTable(
  source,
  ["Área", "Comportamiento", "Código fuente principal", "Pruebas automatizadas", "IDs de casos manuales"],
  sourceRows,
  "SourceMapTable",
);
setWidths(source, [130, 300, 360, 360, 210], sourceRows.length + 1);
source.getRange(`A2:E${sourceRows.length + 1}`).format.rowHeightPx = 70;

writeTable(
  guide,
  ["Tema", "Guía"],
  guideRows,
  "RunGuideTable",
);
setWidths(guide, [180, 760], guideRows.length + 1);
guide.getRange(`A2:B${guideRows.length + 1}`).format.rowHeightPx = 58;

buildOverview(overview, localizedCases.length);

for (const sheet of [manual, setup, source, guide]) {
  sheet.getUsedRange().format.autofitRows();
}

const overviewInspect = await workbook.inspect({
  kind: "table",
  sheetId: "Resumen",
  range: "A1:K22",
  include: "values,formulas",
  tableMaxRows: 22,
  tableMaxCols: 11,
});
console.log("OVERVIEW_INSPECT");
console.log(overviewInspect.ndjson);

const caseInspect = await workbook.inspect({
  kind: "table",
  sheetId: "Casos Manuales",
  range: "A1:Q12",
  include: "values",
  tableMaxRows: 12,
  tableMaxCols: 17,
  tableMaxCellChars: 120,
});
console.log("MANUAL_CASES_INSPECT");
console.log(caseInspect.ndjson);

const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 300 },
  summary: "final formula error scan",
});
console.log("FORMULA_ERROR_SCAN");
console.log(errors.ndjson);

const previewSpecs = [
  ["Resumen", "A1:K22"],
  ["Casos Manuales", "A1:Q12"],
  ["Datos de Prueba", `A1:E${setupRows.length + 1}`],
  ["Mapa de Fuentes", `A1:E${sourceRows.length + 1}`],
  ["Guía de Ejecución", `A1:B${guideRows.length + 1}`],
];

for (const [sheetName, range] of previewSpecs) {
  const blob = await workbook.render({ sheetName, range, scale: 1, format: "png" });
  const previewBytes = new Uint8Array(await blob.arrayBuffer());
  const fileName = `${sheetName.toLowerCase().replaceAll(" ", "_")}_preview.png`;
  await fs.writeFile(path.join(outputDir, fileName), previewBytes);
}

await fs.mkdir(outputDir, { recursive: true });
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
console.log(`SAVED ${outputPath}`);
