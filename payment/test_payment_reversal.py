from __future__ import annotations

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.urls import reverse
from tenant_client.test_utils import FastTenantTestCase

from clients.models import BalanceTransaction, Client, CreditTransaction
from clients.services import balance_service
from clients.services.credit_payment_service import (
    get_open_credit_orders_for_credit_management,
)
from invoice.models import Invoice, InvoiceOrderLink, InvoiceStatus
from orders.models import Order, OrderStatus
from orders.services.order_split_service import OrderSplitError, split_order
from payment import reversal_service, services
from payment.models import (
    PAYMENT_ENTRY_KIND_PAYMENT,
    PAYMENT_ENTRY_KIND_REVERSAL,
    Payment,
)
from payment.services import PaymentRequestData

User = get_user_model()


class PaymentReversalMatrixTests(FastTenantTestCase):
    def setUp(self):
        super().setUp()
        self.manager = User.objects.create_user(
            username='manager_user',
            password='password123',
            is_staff=True,
        )
        self.collector = User.objects.create_user(
            username='collector_user',
            password='password123',
            is_staff=False,
        )
        self.client_account = Client.objects.create(
            name='Cliente Prueba',
            type='individual',
            can_pay_with_credit=True,
            credit_limit=Decimal('5000.00'),
            current_debt=Decimal('0.00'),
            balance=Decimal('0.00'),
        )

    def _create_order(
        self,
        total: Decimal = Decimal('100.00'),
        order_type: str = 'contado',
        status: str = OrderStatus.PENDING.value,
        client: Client | None = None,
    ) -> Order:
        return Order.objects.create(
            client=client or self.client_account,
            subtotal_amount=total,
            total_amount=total,
            type=order_type,
            status=status,
        )

    def test_reverse_cash_payment_at_purchase_converts_to_credit_debt(self):
        order = self._create_order(total=Decimal('150.00'))
        payload = PaymentRequestData(payment_method='cash', amount=Decimal('150.00'))
        resp, status_code = services.process_payment_request(order, payload, self.manager)
        self.assertEqual(status_code, 200)
        original = Payment.objects.get(pk=resp['payment_id'])

        plan = reversal_service.plan_payment_reversal(original.pk)
        self.assertTrue(plan.can_reverse)
        self.assertEqual(plan.order_paid_after, Decimal('0.00'))
        self.assertEqual(plan.order_unpaid_after, Decimal('150.00'))
        self.assertEqual(plan.order_credit_after, Decimal('150.00'))

        token = reversal_service.sign_reversal_token('payment', original.pk, plan.fingerprint)
        reversal = reversal_service.execute_payment_reversal(
            original.pk, self.manager, 'Cobro duplicado', preview_token=token
        )

        original.refresh_from_db()
        self.client_account.refresh_from_db()
        annotated_order = Order.objects.with_payment_totals().get(pk=order.pk)

        self.assertEqual(original.status, 'completed')
        self.assertEqual(original.entry_kind, PAYMENT_ENTRY_KIND_PAYMENT)
        self.assertEqual(reversal.entry_kind, PAYMENT_ENTRY_KIND_REVERSAL)
        self.assertEqual(reversal.reversal_of_id, original.pk)
        self.assertEqual(annotated_order.total_paid, Decimal('0.00'))
        self.assertEqual(Order.objects.get(pk=order.pk).total_paid, Decimal('0.00'))
        self.assertEqual(self.client_account.current_debt, Decimal('150.00'))
        self.assertIn(order.pk, [o.pk for o in get_open_credit_orders_for_credit_management(self.client_account)])

    def test_reverse_payment_with_excess_removes_excess_and_blocks_if_spent(self):
        order = self._create_order(total=Decimal('100.00'))
        payload = PaymentRequestData(
            payment_method='cash',
            amount=Decimal('100.00'),
            cantidad_cobrada=Decimal('140.00'),
        )
        resp, status_code = services.process_payment_request(order, payload, self.manager)
        self.assertEqual(status_code, 200)
        original = Payment.objects.get(pk=resp['payment_id'])

        self.client_account.refresh_from_db()
        self.assertEqual(self.client_account.balance, Decimal('40.00'))

        # Spend $30 of that excess on a newer order
        order2 = self._create_order(total=Decimal('30.00'))
        resp2, status2 = services.process_payment_request(
            order2,
            PaymentRequestData(payment_method='balance', amount=Decimal('30.00')),
            self.manager,
        )
        self.assertEqual(status2, 200)
        payment2 = Payment.objects.get(pk=resp2['payment_id'])

        # Trying to reverse order1 first must block ($10 available < $40 excess)
        blocked_plan = reversal_service.plan_payment_reversal(original.pk)
        self.assertFalse(blocked_plan.can_reverse)
        self.assertEqual(blocked_plan.balance_effects[0].shortage, Decimal('30.00'))

        # Step 1: reverse newer balance payment first (restores $30 -> balance $40)
        plan2 = reversal_service.plan_payment_reversal(payment2.pk)
        self.assertTrue(plan2.can_reverse)
        reversal_service.execute_payment_reversal(
            payment2.pk, self.manager, 'Desmantelar cadena', require_token=False
        )
        self.client_account.refresh_from_db()
        self.assertEqual(self.client_account.balance, Decimal('40.00'))

        # Step 2: now reverse order1 payment (removes $40 excess -> balance $0)
        plan1 = reversal_service.plan_payment_reversal(original.pk)
        self.assertTrue(plan1.can_reverse)
        reversal_service.execute_payment_reversal(
            original.pk, self.manager, 'Cancelar pago original', require_token=False
        )
        self.client_account.refresh_from_db()
        self.assertEqual(self.client_account.balance, Decimal('0.00'))
        self.assertEqual(self.client_account.current_debt, Decimal('130.00'))

    def test_two_step_balance_deposit_and_order_saldo_payment(self):
        deposit = balance_service.add_balance(
            client=self.client_account,
            amount=Decimal('200.00'),
            transaction_type='deposit',
            user=self.manager,
            notes='Abono inicial',
        )
        order = self._create_order(total=Decimal('120.00'))
        resp, status_code = services.process_payment_request(
            order,
            PaymentRequestData(payment_method='balance', amount=Decimal('120.00')),
            self.manager,
        )
        self.assertEqual(status_code, 200)
        saldo_payment = Payment.objects.get(pk=resp['payment_id'])

        # Cancelling deposit while $120 is spent must block ($80 < $200)
        blocked_dep = reversal_service.plan_balance_deposit_reversal(deposit.pk)
        self.assertFalse(blocked_dep.can_reverse)
        self.assertEqual(blocked_dep.shortage, Decimal('120.00'))

        # Step 1: reverse order saldo payment -> restores $120 (balance $200), order becomes credit debt
        reversal_service.execute_payment_reversal(
            saldo_payment.pk, self.manager, 'Error en pago con saldo', require_token=False
        )
        self.client_account.refresh_from_db()
        self.assertEqual(self.client_account.balance, Decimal('200.00'))
        self.assertEqual(self.client_account.current_debt, Decimal('120.00'))

        # Step 2: reverse standalone deposit -> balance drops to $0
        dep_plan = reversal_service.plan_balance_deposit_reversal(deposit.pk)
        self.assertTrue(dep_plan.can_reverse)
        dep_token = reversal_service.sign_reversal_token('deposit', deposit.pk, dep_plan.fingerprint)
        reversal_tx = reversal_service.execute_balance_deposit_reversal(
            deposit.pk, self.manager, 'Abono cancelado', preview_token=dep_token
        )
        self.client_account.refresh_from_db()
        self.assertEqual(reversal_tx.transaction_type, 'deposit_reversal')
        self.assertEqual(reversal_tx.reverses_transaction_id, deposit.pk)
        self.assertEqual(self.client_account.balance, Decimal('0.00'))

    def test_mixed_saldo_plus_cash_leaves_order_partially_paid(self):
        balance_service.add_balance(
            client=self.client_account,
            amount=Decimal('60.00'),
            transaction_type='deposit',
            user=self.manager,
        )
        order = self._create_order(total=Decimal('100.00'))
        resp, status_code = services.process_payment_request(
            order,
            PaymentRequestData(
                payments_data=[
                    {'payment_method': 'balance', 'amount': '60.00'},
                    {'payment_method': 'cash', 'amount': '40.00'},
                ]
            ),
            self.manager,
        )
        self.assertEqual(status_code, 200)
        saldo_payment = order.payments.get(method='balance')

        reversal_service.execute_payment_reversal(
            saldo_payment.pk, self.manager, 'Revertir parte de saldo', require_token=False
        )
        self.client_account.refresh_from_db()
        refreshed_order = Order.objects.get(pk=order.pk)
        self.assertEqual(self.client_account.balance, Decimal('60.00'))
        self.assertEqual(refreshed_order.total_paid, Decimal('40.00'))
        self.assertEqual(self.client_account.current_debt, Decimal('60.00'))

    def test_multi_order_credit_settlement_with_excess_removes_excess_once(self):
        order1 = self._create_order(total=Decimal('100.00'), order_type='credito')
        order2 = self._create_order(total=Decimal('100.00'), order_type='credito')
        services.process_payment_request(order1, PaymentRequestData(order_type='credito'), self.manager)
        services.process_payment_request(order2, PaymentRequestData(order_type='credito'), self.manager)

        result = services.pay_client_orders(
            client=self.client_account,
            orders=[order1, order2],
            payment_method='cash',
            amount=Decimal('250.00'),
            request_user=self.manager,
        )
        p1, p2 = result['payments']
        self.client_account.refresh_from_db()
        self.assertEqual(self.client_account.balance, Decimal('50.00'))
        self.assertEqual(self.client_account.current_debt, Decimal('0.00'))

        # First reversal removes $50 excess and restores $100 debt
        reversal_service.execute_payment_reversal(
            p1.pk, self.manager, 'Revertir pago 1', require_token=False
        )
        self.client_account.refresh_from_db()
        self.assertEqual(self.client_account.balance, Decimal('0.00'))
        self.assertEqual(self.client_account.current_debt, Decimal('100.00'))

        # Second reversal sees excess already removed and restores second $100 debt
        plan2 = reversal_service.plan_payment_reversal(p2.pk)
        self.assertTrue(plan2.can_reverse)
        self.assertTrue(plan2.excess_already_removed)
        self.assertEqual(plan2.excess_amount, Decimal('0.00'))
        reversal_service.execute_payment_reversal(
            p2.pk, self.manager, 'Revertir pago 2', require_token=False
        )
        self.client_account.refresh_from_db()
        self.assertEqual(self.client_account.balance, Decimal('0.00'))
        self.assertEqual(self.client_account.current_debt, Decimal('200.00'))

    def test_stale_preview_authorization_invoice_sync_and_split_block(self):
        order = self._create_order(total=Decimal('100.00'))
        resp, _ = services.process_payment_request(
            order,
            PaymentRequestData(payment_method='cash', amount=Decimal('100.00')),
            self.manager,
        )
        payment = Payment.objects.get(pk=resp['payment_id'])

        invoice = Invoice.objects.create(
            client=self.client_account,
            amount=Decimal('100.00'),
            folio='F-100',
            status=InvoiceStatus.ACTIVE,
        )
        link = InvoiceOrderLink.objects.create(invoice=invoice, order=order, is_paid=True)

        # Non-manager blocked
        with self.assertRaises(PermissionDenied):
            reversal_service.execute_payment_reversal(
                payment.pk, self.collector, 'Sin permiso', require_token=False
            )

        # Stale preview token rejected
        plan = reversal_service.plan_payment_reversal(payment.pk)
        token = reversal_service.sign_reversal_token('payment', payment.pk, plan.fingerprint)
        self.client_account.current_debt = Decimal('25.00')
        self.client_account.save(update_fields=['current_debt'])
        with self.assertRaises(reversal_service.StaleReversalPreviewError):
            reversal_service.execute_payment_reversal(
                payment.pk, self.manager, 'Motivo', preview_token=token
            )

        # Execute with fresh plan
        fresh_plan = reversal_service.plan_payment_reversal(payment.pk)
        fresh_token = reversal_service.sign_reversal_token('payment', payment.pk, fresh_plan.fingerprint)
        reversal_service.execute_payment_reversal(
            payment.pk, self.manager, 'Motivo válido', preview_token=fresh_token
        )

        link.refresh_from_db()
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, InvoiceStatus.ACTIVE)
        self.assertFalse(link.is_paid)
        self.assertEqual(Decimal(str(invoice.total_payments)), Decimal('0.00'))

        # Order split blocked when reversal history exists
        with self.assertRaises(OrderSplitError):
            split_order(order, {}, self.manager)

    def test_views_enforce_manager_auth_and_preview_post_flow(self):
        order = self._create_order(total=Decimal('80.00'))
        resp, _ = services.process_payment_request(
            order,
            PaymentRequestData(payment_method='cash', amount=Decimal('80.00')),
            self.manager,
        )
        payment = Payment.objects.get(pk=resp['payment_id'])

        self.client.force_login(self.collector)
        self.assertEqual(self.client.get(reverse('payment:list_payments')).status_code, 403)
        self.assertEqual(
            self.client.get(reverse('payment:reverse_payment_preview', args=[payment.pk])).status_code,
            403,
        )

        self.client.force_login(self.manager)
        preview_url = reverse('payment:reverse_payment_preview', args=[payment.pk])
        get_resp = self.client.get(preview_url)
        self.assertEqual(get_resp.status_code, 200)
        self.assertEqual(Payment.objects.reversals().count(), 0)

        token = get_resp.context['preview_token']
        post_resp = self.client.post(
            preview_url,
            {'preview_token': token, 'reason': 'Cancelado desde UI'},
        )
        self.assertEqual(post_resp.status_code, 302)
        self.assertEqual(Payment.objects.reversals().count(), 1)

        # Duplicate confirmation cannot create a second reversal
        with self.assertRaises(reversal_service.ReversalBlockedError):
            reversal_service.execute_payment_reversal(
                payment.pk,
                self.manager,
                'Intento duplicado',
                require_token=False,
            )
        self.assertEqual(Payment.objects.reversals().count(), 1)

        # Client detail order table shows Pagos link for manager, hides for collector
        detail_url = reverse('clients:detail', args=[self.client_account.pk])
        order_payments_url = reverse('payment:order_payments', args=[order.pk])
        self.assertContains(self.client.get(detail_url), order_payments_url)
        self.client.force_login(self.collector)
        self.assertNotContains(self.client.get(detail_url), order_payments_url)

    def test_cancel_order_after_payment_reversal_does_not_duplicate_effects(self):
        from orders import services as order_services

        order = self._create_order(total=Decimal('100.00'))
        resp, status_code = services.process_payment_request(
            order,
            PaymentRequestData(
                payment_method='cash',
                amount=Decimal('100.00'),
                cantidad_cobrada=Decimal('150.00'),
            ),
            self.manager,
        )
        self.assertEqual(status_code, 200)
        payment = Payment.objects.get(pk=resp['payment_id'])
        self.client_account.refresh_from_db()
        self.assertEqual(self.client_account.balance, Decimal('50.00'))

        # Step 1: Reverse payment (removes $50 excess, creates $100 credit debt)
        reversal_service.execute_payment_reversal(
            payment.pk,
            self.manager,
            'Pago equivocado',
            require_token=False,
        )
        self.client_account.refresh_from_db()
        self.assertEqual(self.client_account.balance, Decimal('0.00'))
        self.assertEqual(self.client_account.current_debt, Decimal('100.00'))

        # Step 2: Cancel order (must NOT double-remove excess or leave debt)
        cancel_res = order_services.cancel_order(order=order, user=self.manager)
        self.assertTrue(cancel_res['success'])
        self.client_account.refresh_from_db()
        payment.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.CANCELLED.value)
        self.assertEqual(self.client_account.balance, Decimal('0.00'))
        self.assertEqual(self.client_account.current_debt, Decimal('0.00'))
        self.assertEqual(payment.status, 'completed')
        self.assertEqual(Payment.objects.reversals().count(), 1)
        self.assertEqual(
            BalanceTransaction.objects.filter(
                client=self.client_account,
                transaction_type='added_in_order_reversal',
            ).count(),
            1,
        )

    def test_signed_totals_across_invoices_branches_sales_snapshot_and_pdf(self):
        from django.utils import timezone
        from clients.services import corporate_branch_service
        from orders import services as order_services
        from orders.services.receipt_pdf_service import _payments_table

        order = self._create_order(total=Decimal('120.00'))
        invoice = Invoice.objects.create(
            client=self.client_account,
            amount=Decimal('120.00'),
            identifier='INV-SIGNED-1',
            folio='F-SIGNED-1',
            status=InvoiceStatus.ACTIVE,
        )
        InvoiceOrderLink.objects.create(invoice=invoice, order=order)

        resp, _ = services.process_payment_request(
            order,
            PaymentRequestData(payment_method='cash', amount=Decimal('120.00')),
            self.manager,
        )
        payment = Payment.objects.get(pk=resp['payment_id'])

        reversal_service.execute_payment_reversal(
            payment.pk,
            self.manager,
            'Reversión para verificar totales',
            require_token=False,
        )

        # InvoiceQuerySet.with_balance_totals() agrees with signed net total
        annotated_inv = Invoice.objects.with_balance_totals().get(pk=invoice.pk)
        self.assertEqual(annotated_inv.paid_total, Decimal('0.00'))
        self.assertEqual(annotated_inv.unpaid_balance, Decimal('120.00'))

        # Sales snapshot net total is 0.00 and receipt count is 1 (not 2)
        today = timezone.localdate()
        snapshot = order_services.get_sales_snapshot(today, today)
        cash_row = next(r for r in snapshot['payment_methods'] if r['method'] == 'cash')
        self.assertEqual(cash_row['total_amount'], Decimal('0.00'))
        self.assertEqual(cash_row['payment_count'], 1)

        # Corporate branch payment totals use signed net amounts
        branch_totals = corporate_branch_service._get_payment_totals(
            [self.client_account],
            date_from=today,
            date_to=today,
        )
        self.assertEqual(branch_totals.get(self.client_account.pk, Decimal('0.00')), Decimal('0.00'))

        # Receipt PDF table includes negative formatted reversal row
        table = _payments_table(order)
        cell_values = [cell for row in table._cellvalues for cell in row]
        self.assertIn('-$120.00', cell_values)

    def test_historical_ambiguous_excess_and_legacy_reversed_rows(self):
        order = self._create_order(total=Decimal('100.00'))
        legacy_payment = Payment.objects.create(
            amount=Decimal('100.00'),
            method='cash',
            client=self.client_account,
            order=order,
            status='completed',
            created_by=self.manager,
        )
        BalanceTransaction.objects.create(
            client=self.client_account,
            transaction_type='added_in_order',
            amount=Decimal('25.00'),
            balance_before=Decimal('0.00'),
            balance_after=Decimal('25.00'),
            reference_order=order,
            created_by=self.manager,
        )
        plan = reversal_service.plan_payment_reversal(legacy_payment.pk)
        self.assertFalse(plan.can_reverse)
        self.assertTrue(any('revisión' in r.lower() for r in plan.blocking_reasons))

        # Legacy status='reversed' row contributes zero and cannot be reversed again
        order2 = self._create_order(total=Decimal('60.00'))
        old_reversed = Payment(
            amount=Decimal('60.00'),
            method='cash',
            client=self.client_account,
            order=order2,
            status='reversed',
            created_by=self.manager,
        )
        old_reversed.save(apply_accounting=False)
        self.assertEqual(order2.total_paid, Decimal('0.00'))
        self.assertEqual(
            Order.objects.with_payment_totals().get(pk=order2.pk).total_paid,
            Decimal('0.00'),
        )
        self.assertFalse(reversal_service.plan_payment_reversal(old_reversed.pk).can_reverse)

    def test_lowered_credit_limit_does_not_block_reversal_and_updates_credit_report(self):
        from clients.services.credit_report_service import get_client_credit_report

        order = self._create_order(total=Decimal('200.00'))
        resp, _ = services.process_payment_request(
            order,
            PaymentRequestData(payment_method='cash', amount=Decimal('200.00')),
            self.manager,
        )
        payment = Payment.objects.get(pk=resp['payment_id'])

        # Disable credit and lower limit to 0 before reversing
        self.client_account.can_pay_with_credit = False
        self.client_account.credit_limit = Decimal('0.00')
        self.client_account.save(update_fields=['can_pay_with_credit', 'credit_limit'])

        reversal_service.execute_payment_reversal(
            payment.pk,
            self.manager,
            'Reversión con límite reducido',
            require_token=False,
        )
        self.client_account.refresh_from_db()
        self.assertEqual(self.client_account.current_debt, Decimal('200.00'))

        credit_report = get_client_credit_report(client=self.client_account)
        self.assertEqual(credit_report.current_credit, Decimal('200.00'))
        self.assertEqual(credit_report.open_credit_total, Decimal('200.00'))

    def test_reverse_payment_on_legacy_split_child_is_blocked_to_prevent_double_debt(self):
        from orders.models import OrderSplit

        # Parent credit order still holding full unsplit debt ($200)
        parent = self._create_order(total=Decimal('200.00'), order_type='credito')
        resp, status_code = services.process_payment_request(
            parent,
            PaymentRequestData(order_type='credito'),
            self.manager,
        )
        self.assertEqual(status_code, 200)
        self.client_account.refresh_from_db()
        self.assertEqual(self.client_account.current_debt, Decimal('200.00'))

        # Legacy split child with no pending_credit marker and no CreditTransaction
        child = self._create_order(
            total=Decimal('100.00'),
            order_type='contado',
            status=OrderStatus.COMPLETED.value,
        )
        OrderSplit.objects.create(
            source_order=parent,
            child_order=child,
            split_by=self.manager,
        )
        child_payment, error = services.process_single_payment(
            order=child,
            payment_method='cash',
            amount=Decimal('100.00'),
            request_user=self.manager,
        )
        self.assertIsNone(error)
        assert child_payment is not None

        plan = reversal_service.plan_payment_reversal(child_payment.pk)
        self.assertFalse(plan.can_reverse)
        self.assertTrue(
            any('división histórica' in reason for reason in plan.blocking_reasons),
            plan.blocking_reasons,
        )

        with self.assertRaises(reversal_service.ReversalBlockedError):
            reversal_service.execute_payment_reversal(
                child_payment.pk,
                self.manager,
                'Intentar revertir pago de división histórica',
                require_token=False,
            )

        self.client_account.refresh_from_db()
        self.assertEqual(self.client_account.current_debt, Decimal('200.00'))
