import csv
import io
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db.models import Sum
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone
from tenant_client.test_utils import FastTenantTestCase

from clients.services.corporate_branch_service import build_corporate_branch_workspace

from .forms import AddressInlineForm
from .models import (
    Address,
    BalanceTransaction,
    Client,
    ClientBillingFrecuency,
    ClientCreditConfig,
    Contact,
    CreditTransaction,
    InvoiceData,
)
from .services.csv_import_service import (
    _get_or_create_corporate,
    export_clients_to_csv,
    get_clients_csv_template,
    import_clients_from_csv,
)
from .services.client_detail_service import build_client_detail_snapshot
from core.models import Transport
from invoice.models import Invoice, InvoiceOrderLink
from orders.models import Order, OrderStatus
from payment.models import Payment
from product.models import Product, ProductClientPrice
from routes.models import Route, RouteClient

User = get_user_model()


class CorporateBranchWorkspaceServiceTests(FastTenantTestCase):
    def setUp(self) -> None:
        self.corporate = Client.objects.create(
            name='Corporativo Agua Norte',
            type='corporate',
        )
        self.branch_a = Client.objects.create(
            name='Sucursal A',
            type='branch',
            corporate=self.corporate,
            current_debt=Decimal('30.00'),
            active=True,
        )
        self.branch_b = Client.objects.create(
            name='Sucursal B',
            type='branch',
            corporate=self.corporate,
            current_debt=Decimal('70.00'),
            active=True,
        )
        self.other_corporate = Client.objects.create(
            name='Corporativo Otro',
            type='corporate',
        )
        self.other_branch = Client.objects.create(
            name='Sucursal Externa',
            type='branch',
            corporate=self.other_corporate,
            active=True,
        )

        self.branch_a_completed = self._create_order(
            client=self.branch_a,
            status=OrderStatus.COMPLETED.value,
            amount=Decimal('100.00'),
            day=5,
        )
        self.branch_a_pending = self._create_order(
            client=self.branch_a,
            status=OrderStatus.PENDING.value,
            amount=Decimal('50.00'),
            day=6,
        )
        self.branch_a_cancelled = self._create_order(
            client=self.branch_a,
            status=OrderStatus.CANCELLED.value,
            amount=Decimal('999.00'),
            day=7,
        )
        self.branch_b_completed = self._create_order(
            client=self.branch_b,
            status=OrderStatus.COMPLETED.value,
            amount=Decimal('200.00'),
            day=8,
        )
        self.branch_a_outside_range = self._create_order(
            client=self.branch_a,
            status=OrderStatus.COMPLETED.value,
            amount=Decimal('500.00'),
            month=6,
            day=30,
        )

        self.branch_a_payment = Payment.objects.create(
            client=self.branch_a,
            order=self.branch_a_completed,
            amount=Decimal('80.00'),
            method='cash',
            status='completed',
        )
        self.pending_credit_payment = Payment.objects.create(
            client=self.branch_a,
            order=self.branch_a_pending,
            amount=Decimal('50.00'),
            method='pending_credit',
            status='pending',
        )
        self.branch_b_payment = Payment.objects.create(
            client=self.branch_b,
            order=self.branch_b_completed,
            amount=Decimal('200.00'),
            method='bank_transfer',
            status='completed',
        )
        self._set_payment_date(self.branch_a_payment, day=9)
        self._set_payment_date(self.pending_credit_payment, day=10)
        self._set_payment_date(self.branch_b_payment, day=11)

    def _create_order(
        self,
        *,
        client: Client,
        status: str,
        amount: Decimal,
        day: int,
        month: int = 7,
        year: int = 2026,
    ) -> Order:
        order = Order.objects.create(
            client=client,
            status=status,
            total_amount=amount,
        )
        Order.objects.filter(pk=order.pk).update(
            order_date=timezone.make_aware(datetime(year, month, day, 9, 0)),
        )
        order.refresh_from_db()
        return order

    def _set_payment_date(
        self,
        payment: Payment,
        *,
        day: int,
        month: int = 7,
        year: int = 2026,
    ) -> None:
        Payment.objects.filter(pk=payment.pk).update(
            date=timezone.make_aware(datetime(year, month, day, 12, 0)),
        )
        payment.refresh_from_db()

    def test_build_workspace_defaults_to_first_active_branch_and_current_month(self) -> None:
        context = build_corporate_branch_workspace(
            self.corporate,
            {},
            today=date(2026, 7, 22),
        )

        self.assertEqual(context['selected_branch'], self.branch_a)
        self.assertEqual(context['active_tab'], 'summary')
        self.assertEqual(context['date_from'], date(2026, 7, 1))
        self.assertEqual(context['date_to'], date(2026, 7, 31))

    def test_build_workspace_summarizes_branch_orders_and_payments(self) -> None:
        context = build_corporate_branch_workspace(
            self.corporate,
            {'branch': str(self.branch_a.pk)},
            today=date(2026, 7, 22),
        )

        self.assertEqual(context['corporate_summary']['total_orders'], 4)
        self.assertEqual(context['corporate_summary']['total_sales'], Decimal('350.00'))
        self.assertEqual(context['corporate_summary']['total_payments'], Decimal('280.00'))
        self.assertEqual(context['corporate_summary']['total_current_debt'], Decimal('100.00'))
        self.assertEqual(context['selected_branch_summary']['order_count'], 3)
        self.assertEqual(context['selected_branch_summary']['sales_total'], Decimal('150.00'))
        self.assertEqual(context['selected_branch_summary']['payment_total'], Decimal('80.00'))
        self.assertNotIn(self.branch_a_outside_range, context['orders_page'].object_list)

    def test_build_workspace_ignores_branch_id_from_other_corporate(self) -> None:
        context = build_corporate_branch_workspace(
            self.corporate,
            {'branch': str(self.other_branch.pk)},
            today=date(2026, 7, 22),
        )

        self.assertEqual(context['selected_branch'], self.branch_a)



class ClientBillingInheritanceTestCase(FastTenantTestCase):
    """Business-rule focused tests for branch billing inheritance."""

    def setUp(self):
        self.corporate = Client.objects.create(
            name="Corporate Client",
            type="corporate",
            requires_billing=True,
            active=True,
        )
        InvoiceData.objects.create(
            client=self.corporate,
            rfc="CORP123456ABC",
            razon_social="Corporativo SA de CV",
        )
        Address.objects.create(
            client=self.corporate,
            type="billing",
            street="Av. Corporativa 100",
            municipality="Querétaro",
            state="Querétaro",
            zip_code="76000",
            country="México",
            active=True,
        )
        ClientBillingFrecuency.objects.create(
            client=self.corporate,
            frequency="monthly",
            billing_date="first_day",
            start_date=date(2026, 7, 13),
            is_active=True,
        )

        self.branch = Client.objects.create(
            name="Branch Client",
            type="branch",
            corporate=self.corporate,
            active=True,
        )

        self.branch_with_own_billing = Client.objects.create(
            name="Branch With Own Billing",
            type="branch",
            corporate=self.corporate,
            credit_override_enabled=True,
            requires_billing=True,
            active=True,
        )

    def test_corporate_ready_with_all_components(self):
        billing = self.corporate.billing_info
        self.assertTrue(billing.is_complete)
        self.assertEqual(billing.source, 'own')

    def test_corporate_not_ready_when_missing_any_component(self):
        corporate = Client.objects.create(
            name="Corp Missing Address",
            type="corporate",
            requires_billing=True,
            active=True,
        )
        InvoiceData.objects.create(
            client=corporate,
            rfc="MISS123456",
            razon_social="Missing SA",
        )
        ClientBillingFrecuency.objects.create(
            client=corporate,
            frequency="monthly",
            billing_date="first_day",
            start_date=date(2026, 7, 13),
            is_active=True,
        )

        billing = corporate.billing_info
        self.assertFalse(billing.is_complete)
        self.assertEqual(billing.source, 'none')

    def test_branch_inherits_when_corporate_ready(self):
        billing = self.branch.billing_info
        self.assertTrue(billing.is_complete)
        self.assertEqual(billing.source, 'corporate')

    def test_branch_inheritance_not_ready_if_corporate_incomplete(self):
        corp_incomplete = Client.objects.create(
            name="Corp Incomplete",
            type="corporate",
            requires_billing=True,
            active=True,
        )
        InvoiceData.objects.create(
            client=corp_incomplete,
            rfc="INC123456",
            razon_social="Incomplete SA",
        )
        ClientBillingFrecuency.objects.create(
            client=corp_incomplete,
            frequency="monthly",
            billing_date="first_day",
            start_date=date(2026, 7, 13),
            is_active=True,
        )
        branch = Client.objects.create(
            name="Branch Inherit Incomplete",
            type="branch",
            corporate=corp_incomplete,
            active=True,
        )

        billing = branch.billing_info
        self.assertFalse(billing.is_complete)
        self.assertEqual(billing.source, 'corporate')

    def test_branch_always_uses_corporate_even_with_own_complete_data(self):
        InvoiceData.objects.create(
            client=self.branch_with_own_billing,
            rfc="BRANCH123456XYZ",
            razon_social="Sucursal SA de CV",
        )
        Address.objects.create(
            client=self.branch_with_own_billing,
            type="billing",
            street="Av. Sucursal 200",
            municipality="Querétaro",
            state="Querétaro",
            zip_code="76100",
            country="México",
            active=True,
        )
        ClientBillingFrecuency.objects.create(
            client=self.branch_with_own_billing,
            frequency="monthly",
            billing_date="last_day",
            start_date=date(2026, 7, 13),
            is_active=True,
        )

        billing = self.branch_with_own_billing.billing_info
        self.assertTrue(billing.is_complete)
        self.assertEqual(billing.source, 'corporate')
        self.assertEqual(billing.effective.data, self.corporate.invoice_data)
        self.assertEqual(
            billing.effective.address,
            self.corporate.addresses.get(type='billing'),
        )
        self.assertEqual(billing.effective.frequency, self.corporate.invoice_schedule)

    def test_branch_ignores_incomplete_own_data_when_corporate_ready(self):
        InvoiceData.objects.create(
            client=self.branch_with_own_billing,
            rfc="PART123456",
            razon_social="Parcial SA",
        )

        billing = self.branch_with_own_billing.billing_info
        self.assertTrue(billing.is_complete)
        self.assertEqual(billing.source, 'corporate')
        self.assertEqual(billing.effective.data, self.corporate.invoice_data)


class ClientCreditManagementOrderScopeTests(FastTenantTestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username='credit-management-scope-user',
            password='testpass123',
        )
        self.client.force_login(self.user)
        self.corporate = Client.objects.create(
            name='Corporativo alcance credito',
            type='corporate',
            credit_limit=Decimal('1000.00'),
            can_pay_with_credit=True,
        )
        self.branch = Client.objects.create(
            name='Sucursal alcance credito',
            type='branch',
            corporate=self.corporate,
            credit_override_enabled=False,
        )
        self.other_corporate = Client.objects.create(
            name='Corporativo fuera alcance credito',
            type='corporate',
            credit_limit=Decimal('1000.00'),
            can_pay_with_credit=True,
        )
        self.other_branch = Client.objects.create(
            name='Sucursal fuera alcance credito',
            type='branch',
            corporate=self.other_corporate,
            credit_override_enabled=False,
        )

    def _credit_order(
        self,
        client: Client,
        amount: Decimal,
        *,
        order_date: datetime,
        credit_account: Client | None = None,
        status: str = OrderStatus.COMPLETED.value,
    ) -> Order:
        order = Order.objects.create(
            client=client,
            status=status,
            total_amount=amount,
            type='credito',
        )
        Order.objects.filter(pk=order.pk).update(order_date=order_date)
        order.refresh_from_db()
        pending_credit = Payment.objects.create(
            client=client,
            order=order,
            amount=amount,
            method='pending_credit',
            status='pending',
            created_by=self.user,
        )
        CreditTransaction.objects.create(
            client=credit_account or client.get_credit_account(),
            transaction_type='purchase',
            amount=amount,
            debt_before=Decimal('0.00'),
            debt_after=amount,
            credit_limit_before=Decimal('1000.00'),
            credit_limit_after=Decimal('1000.00'),
            reference_order=order,
            reference_payment=pending_credit,
            created_by=self.user,
        )
        return order

    def test_branch_scope_lists_own_pending_credit_orders_newest_first(self) -> None:
        from clients.services.credit_payment_service import (
            get_open_credit_orders_for_credit_management,
        )

        older = self._credit_order(
            self.branch,
            Decimal('100.00'),
            order_date=timezone.now() - timedelta(days=2),
            credit_account=self.corporate,
        )
        newer = self._credit_order(
            self.branch,
            Decimal('150.00'),
            order_date=timezone.now() - timedelta(days=1),
            credit_account=self.corporate,
        )

        orders = get_open_credit_orders_for_credit_management(self.branch)

        self.assertEqual([order.pk for order in orders], [newer.pk, older.pk])

    def test_corporate_scope_lists_all_branch_credit_orders_newest_first(self) -> None:
        from clients.services.credit_payment_service import (
            get_open_credit_orders_for_credit_management,
        )

        override_branch = Client.objects.create(
            name='Sucursal credito propio',
            type='branch',
            corporate=self.corporate,
            credit_override_enabled=True,
            credit_limit=Decimal('1000.00'),
            can_pay_with_credit=True,
        )
        inherited_order = self._credit_order(
            self.branch,
            Decimal('100.00'),
            order_date=timezone.now() - timedelta(days=2),
            credit_account=self.corporate,
        )
        override_order = self._credit_order(
            override_branch,
            Decimal('180.00'),
            order_date=timezone.now() - timedelta(days=1),
            credit_account=override_branch,
        )

        orders = get_open_credit_orders_for_credit_management(self.corporate)

        self.assertEqual([order.pk for order in orders], [override_order.pk, inherited_order.pk])

    def test_scope_excludes_paid_cancelled_and_out_of_scope_orders(self) -> None:
        from clients.services.credit_payment_service import (
            get_open_credit_orders_for_credit_management,
        )

        selectable = self._credit_order(
            self.branch,
            Decimal('100.00'),
            order_date=timezone.now() - timedelta(days=1),
            credit_account=self.corporate,
        )
        paid = self._credit_order(
            self.branch,
            Decimal('80.00'),
            order_date=timezone.now(),
            credit_account=self.corporate,
        )
        Payment.objects.create(
            client=self.branch,
            order=paid,
            amount=Decimal('80.00'),
            method='cash',
            status='completed',
            created_by=self.user,
        )
        self._credit_order(
            self.other_branch,
            Decimal('90.00'),
            order_date=timezone.now(),
            credit_account=self.other_corporate,
        )
        self._credit_order(
            self.branch,
            Decimal('70.00'),
            order_date=timezone.now(),
            credit_account=self.corporate,
            status=OrderStatus.CANCELLED.value,
        )

        orders = get_open_credit_orders_for_credit_management(self.corporate)

        self.assertEqual([order.pk for order in orders], [selectable.pk])

    def test_pay_client_orders_allows_corporate_scope_for_branch_credit_orders(self) -> None:
        from clients.services.credit_payment_service import (
            get_open_credit_orders_for_credit_management,
        )
        from payment import services as payment_services

        order = self._credit_order(
            self.branch,
            Decimal('100.00'),
            order_date=timezone.now(),
            credit_account=self.corporate,
        )
        self.corporate.current_debt = Decimal('100.00')
        self.corporate.save(update_fields=['current_debt', 'updated_at'])
        allowed_orders = get_open_credit_orders_for_credit_management(self.corporate)

        result = payment_services.pay_client_orders(
            client=self.corporate,
            orders=[order],
            payment_method='cash',
            amount=Decimal('100.00'),
            request_user=self.user,
            allowed_order_ids=[allowed_order.pk for allowed_order in allowed_orders],
        )

        self.assertEqual(result['selected_total'], Decimal('100.00'))
        self.corporate.refresh_from_db()
        self.assertEqual(self.corporate.current_debt, Decimal('0.00'))
        self.assertTrue(order.payments.filter(method='cash', client=self.branch).exists())

    def test_corporate_balance_payment_spends_corporate_balance_for_branch_order(self) -> None:
        from clients.services.credit_payment_service import (
            get_open_credit_orders_for_credit_management,
        )
        from payment import services as payment_services

        self.corporate.balance = Decimal('120.00')
        self.corporate.current_debt = Decimal('100.00')
        self.corporate.save(update_fields=['balance', 'current_debt', 'updated_at'])
        order = self._credit_order(
            self.branch,
            Decimal('100.00'),
            order_date=timezone.now(),
            credit_account=self.corporate,
        )
        allowed_orders = get_open_credit_orders_for_credit_management(self.corporate)

        payment_services.pay_client_orders(
            client=self.corporate,
            orders=[order],
            payment_method='balance',
            amount=Decimal('100.00'),
            request_user=self.user,
            allowed_order_ids=[allowed_order.pk for allowed_order in allowed_orders],
            payment_client=self.corporate,
        )

        self.corporate.refresh_from_db()
        self.branch.refresh_from_db()
        self.assertEqual(self.corporate.balance, Decimal('20.00'))
        self.assertEqual(self.branch.balance, Decimal('0.00'))
        self.assertTrue(order.payments.filter(method='balance', client=self.corporate).exists())

    def test_pay_credit_requires_selected_orders_for_payment(self) -> None:
        response = self.client.post(
            reverse('clients:pay_credit', args=[self.branch.pk]),
            {
                'client': self.branch.pk,
                'transaction_type': 'payment',
                'amount': '100.00',
                'description': 'Pago recibido',
                'notes': 'Pago recibido con referencia bancaria.',
                'payment_method': 'cash',
            },
        )

        self.assertEqual(response.status_code, 200)

    def test_pay_credit_blocks_underpayment_with_split_guidance(self) -> None:
        order = self._credit_order(
            self.branch,
            Decimal('150.00'),
            order_date=timezone.now(),
            credit_account=self.corporate,
        )
        self.corporate.current_debt = Decimal('150.00')
        self.corporate.save(update_fields=['current_debt', 'updated_at'])

        response = self.client.post(
            reverse('clients:pay_credit', args=[self.branch.pk]),
            {
                'client': self.branch.pk,
                'transaction_type': 'payment',
                'orders': [str(order.pk)],
                'amount': '100.00',
                'description': 'Pago recibido',
                'notes': 'Pago recibido con referencia bancaria.',
                'payment_method': 'cash',
            },
        )

        self.assertEqual(response.status_code, 200)

    def test_pay_credit_rejects_balance_method_for_received_payment(self) -> None:
        self.branch.balance = Decimal('150.00')
        self.branch.save(update_fields=['balance', 'updated_at'])
        self.corporate.current_debt = Decimal('100.00')
        self.corporate.save(update_fields=['current_debt', 'updated_at'])
        order = self._credit_order(
            self.branch,
            Decimal('100.00'),
            order_date=timezone.now(),
            credit_account=self.corporate,
        )

        response = self.client.post(
            reverse('clients:pay_credit', args=[self.branch.pk]),
            {
                'client': self.branch.pk,
                'transaction_type': 'payment',
                'orders': [str(order.pk)],
                'amount': '150.00',
                'description': 'Pago recibido',
                'notes': 'Pago recibido con referencia bancaria.',
                'payment_method': 'balance',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.branch.refresh_from_db()
        self.corporate.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual(self.branch.balance, Decimal('150.00'))
        self.assertEqual(self.corporate.current_debt, Decimal('100.00'))
        self.assertFalse(order.is_paid)

    def test_pay_credit_payment_settles_orders_and_adds_overpayment_to_balance(self) -> None:
        order = self._credit_order(
            self.branch,
            Decimal('150.00'),
            order_date=timezone.now(),
            credit_account=self.corporate,
        )
        self.corporate.current_debt = Decimal('150.00')
        self.corporate.save(update_fields=['current_debt', 'updated_at'])

        response = self.client.post(
            reverse('clients:pay_credit', args=[self.branch.pk]),
            {
                'client': self.branch.pk,
                'transaction_type': 'payment',
                'orders': [str(order.pk)],
                'amount': '200.00',
                'description': 'Pago recibido',
                'notes': 'Pago recibido con referencia bancaria.',
                'payment_method': 'cash',
            },
        )

        self.assertEqual(response.status_code, 302)
        self.corporate.refresh_from_db()
        self.branch.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual(self.corporate.current_debt, Decimal('0.00'))
        self.assertEqual(self.branch.balance, Decimal('50.00'))
        self.assertTrue(order.is_paid)

    def test_pay_credit_payment_uses_submitted_transaction_date(self) -> None:
        order = self._credit_order(
            self.branch,
            Decimal('150.00'),
            order_date=timezone.now(),
            credit_account=self.corporate,
        )
        self.corporate.current_debt = Decimal('150.00')
        self.corporate.save(update_fields=['current_debt', 'updated_at'])

        response = self.client.post(
            reverse('clients:pay_credit', args=[self.branch.pk]),
            {
                'client': self.branch.pk,
                'transaction_type': 'payment',
                'orders': [str(order.pk)],
                'amount': '150.00',
                'date': '2026-07-14',
                'description': 'Pago recibido',
                'notes': 'Pago recibido con referencia bancaria.',
                'payment_method': 'cash',
            },
        )

        self.assertEqual(response.status_code, 302)
        payment = order.payments.get(method='cash')
        payment_date = timezone.localtime(payment.date)
        credit_transaction = CreditTransaction.objects.get(
            reference_order=order,
            transaction_type='payment',
        )
        self.assertEqual(payment_date.date(), date(2026, 7, 14))
        self.assertEqual(credit_transaction.date, date(2026, 7, 14))

    def test_pay_credit_balance_payment_uses_screen_client_balance(self) -> None:
        self.corporate.balance = Decimal('160.00')
        self.corporate.current_debt = Decimal('150.00')
        self.corporate.save(update_fields=['balance', 'current_debt', 'updated_at'])
        order = self._credit_order(
            self.branch,
            Decimal('150.00'),
            order_date=timezone.now(),
            credit_account=self.corporate,
        )

        response = self.client.post(
            reverse('clients:pay_credit', args=[self.corporate.pk]),
            {
                'client': self.corporate.pk,
                'transaction_type': 'payment_from_balance',
                'orders': [str(order.pk)],
                'description': 'Pago con saldo',
                'notes': 'Pago aplicado usando saldo corporativo.',
            },
        )

        self.assertEqual(response.status_code, 302)
        self.corporate.refresh_from_db()
        self.branch.refresh_from_db()
        self.assertEqual(self.corporate.balance, Decimal('10.00'))
        self.assertEqual(self.branch.balance, Decimal('0.00'))
        self.assertEqual(self.corporate.current_debt, Decimal('0.00'))

class ClientSelectedOrderPaymentServiceTests(FastTenantTestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username='selected-pay-user',
            password='testpass123',
        )
        self.customer = Client.objects.create(
            name='Cliente pagos seleccionados',
            active=True,
            credit_limit=Decimal('1000.00'),
            can_pay_with_credit=True,
        )
        self.other_customer = Client.objects.create(
            name='Cliente ajeno',
            active=True,
        )

    def _order(
        self,
        client: Client,
        total: Decimal,
        status: str = OrderStatus.COMPLETED.value,
    ) -> Order:
        return Order.objects.create(
            client=client,
            status=status,
            total_amount=total,
        )

    def test_pay_client_orders_pays_multiple_unpaid_orders(self) -> None:
        from payment import services as payment_services

        first = self._order(self.customer, Decimal('100.00'))
        second = self._order(self.customer, Decimal('80.00'))

        result = payment_services.pay_client_orders(
            client=self.customer,
            orders=[first, second],
            payment_method='cash',
            amount=Decimal('180.00'),
            request_user=self.user,
        )

        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(result['selected_total'], Decimal('180.00'))
        self.assertEqual(result['balance_added'], Decimal('0.00'))
        self.assertTrue(first.is_paid)
        self.assertTrue(second.is_paid)
        self.assertEqual(
            Payment.objects.filter(
                order__in=[first, second],
                method='cash',
                status='completed',
            ).count(),
            2,
        )

    def test_pay_client_orders_blocks_underpayment(self) -> None:
        from payment import services as payment_services

        first = self._order(self.customer, Decimal('100.00'))
        second = self._order(self.customer, Decimal('80.00'))

        with self.assertRaisesRegex(
            payment_services.ClientOrderPaymentError,
            'menor al total seleccionado',
        ):
            payment_services.pay_client_orders(
                client=self.customer,
                orders=[first, second],
                payment_method='cash',
                amount=Decimal('179.99'),
                request_user=self.user,
            )

        self.assertFalse(
            Payment.objects.filter(
                order__in=[first, second],
                method='cash',
            ).exists(),
        )

    def test_pay_client_orders_rejects_order_from_another_client(self) -> None:
        from payment import services as payment_services

        own_order = self._order(self.customer, Decimal('100.00'))
        other_order = self._order(self.other_customer, Decimal('80.00'))

        with self.assertRaisesRegex(
            payment_services.ClientOrderPaymentError,
            'no pertenece al cliente',
        ):
            payment_services.pay_client_orders(
                client=self.customer,
                orders=[own_order, other_order],
                payment_method='cash',
                amount=Decimal('180.00'),
                request_user=self.user,
            )

    def test_pay_client_orders_settles_credit_and_preserves_history(self) -> None:
        from payment import services as payment_services

        self.customer.current_debt = Decimal('100.00')
        self.customer.save(update_fields=['current_debt', 'updated_at'])
        order = self._order(self.customer, Decimal('100.00'))
        order.type = 'credito'
        order.save(update_fields=['type', 'updated_at'])
        pending_credit = Payment.objects.create(
            client=self.customer,
            order=order,
            amount=Decimal('100.00'),
            method='pending_credit',
            status='pending',
            created_by=self.user,
        )
        CreditTransaction.objects.create(
            client=self.customer,
            transaction_type='purchase',
            amount=Decimal('100.00'),
            debt_before=Decimal('0.00'),
            debt_after=Decimal('100.00'),
            credit_limit_before=Decimal('1000.00'),
            credit_limit_after=Decimal('1000.00'),
            reference_order=order,
            reference_payment=pending_credit,
            created_by=self.user,
        )

        payment_services.pay_client_orders(
            client=self.customer,
            orders=[order],
            payment_method='cash',
            amount=Decimal('100.00'),
            request_user=self.user,
        )

        order.refresh_from_db()
        pending_credit.refresh_from_db()
        self.customer.refresh_from_db()
        self.assertEqual(order.type, 'credito')
        self.assertTrue(order.is_paid)
        self.assertEqual(pending_credit.status, 'completed')
        self.assertEqual(self.customer.current_debt, Decimal('0.00'))
        self.assertTrue(
            CreditTransaction.objects.filter(
                reference_order=order,
                transaction_type='payment',
            ).exists(),
        )

    def test_pay_client_orders_adds_overpayment_to_balance(self) -> None:
        from payment import services as payment_services

        first = self._order(self.customer, Decimal('100.00'))
        second = self._order(self.customer, Decimal('80.00'))

        result = payment_services.pay_client_orders(
            client=self.customer,
            orders=[first, second],
            payment_method='cash',
            amount=Decimal('200.00'),
            request_user=self.user,
        )

        self.customer.refresh_from_db()
        self.assertEqual(result['balance_added'], Decimal('20.00'))
        self.assertEqual(self.customer.balance, Decimal('20.00'))
        self.assertTrue(
            BalanceTransaction.objects.filter(
                client=self.customer,
                amount=Decimal('20.00'),
                reference_order=second,
            ).exists(),
        )



class ClientDetailSnapshotServiceTests(FastTenantTestCase):
    def setUp(self) -> None:
        self.client_obj = Client.objects.create(
            name='Cliente snapshot',
            active=True,
        )

    def _build_snapshot(
        self,
        *,
        client: Client | None = None,
        billing_frequency: object | None = None,
        client_invoices: list[object] | None = None,
        pending_payment_data: dict[str, object] | None = None,
        debt_percentage: int = 0,
    ) -> dict[str, object]:
        return build_client_detail_snapshot(
            client=client or self.client_obj,
            billing_frequency=billing_frequency,
            client_invoices=client_invoices or [],
            pending_payment_data=pending_payment_data or {
                'total_overdue_amount': Decimal('0.00'),
            },
            debt_percentage=debt_percentage,
        )

    def _snapshot_card(
        self,
        snapshot: dict[str, object],
        label: str,
    ) -> dict[str, object]:
        return next(
            card
            for card in snapshot['snapshot_cards']
            if card['label'] == label
        )

    def _create_credit_order(
        self,
        *,
        client: Client,
        amount: Decimal,
    ) -> Order:
        return Order.objects.create(
            client=client,
            status=OrderStatus.COMPLETED.value,
            total_amount=amount,
            type='credito',
        )

    def test_snapshot_promotes_financial_risk_only_when_overdue_amount_exists(self) -> None:
        clean_snapshot = self._build_snapshot()
        risky_snapshot = self._build_snapshot(
            pending_payment_data={
                'total_overdue_amount': Decimal('100.00'),
            },
        )

        self.assertFalse(clean_snapshot['has_financial_risk'])
        self.assertTrue(risky_snapshot['has_financial_risk'])
        self.assertEqual(
            risky_snapshot['credit_report_url_label'],
            'Ver reporte de crédito',
        )

    def test_snapshot_does_not_include_next_visit_card(self) -> None:
        snapshot = self._build_snapshot()
        card_labels = [
            card['label']
            for card in snapshot['snapshot_cards']
        ]

        self.assertNotIn('Próxima visita', card_labels)
        self.assertEqual(
            card_labels,
            ['Saldo prepago', 'Deuda actual', 'Crédito', 'Facturación'],
        )

    def test_snapshot_summarizes_credit_usage_when_credit_is_enabled(self) -> None:
        self.client_obj.credit_limit = Decimal('100.00')
        self.client_obj.current_debt = Decimal('20.00')
        self.client_obj.save(update_fields=['credit_limit', 'current_debt', 'updated_at'])

        snapshot = self._build_snapshot(debt_percentage=20)
        credit_card = self._snapshot_card(snapshot, 'Crédito')

        self.assertEqual(credit_card['value'], '20%')
        self.assertEqual(credit_card['note'], 'Disponible: $80.00 de $100.00')

    def test_snapshot_shows_inherited_branch_debt_from_corporate_credit_order(
        self,
    ) -> None:
        corporate = Client.objects.create(
            name='Corporativo snapshot',
            type='corporate',
            credit_limit=Decimal('1000.00'),
            current_debt=Decimal('100.00'),
            can_pay_with_credit=True,
        )
        branch = Client.objects.create(
            name='Sucursal snapshot',
            type='branch',
            corporate=corporate,
            credit_override_enabled=False,
            current_debt=Decimal('0.00'),
        )
        order = self._create_credit_order(client=branch, amount=Decimal('100.00'))
        CreditTransaction.objects.create(
            client=corporate,
            amount=Decimal('100.00'),
            transaction_type='purchase',
            debt_before=Decimal('0.00'),
            debt_after=Decimal('100.00'),
            credit_limit_before=Decimal('1000.00'),
            credit_limit_after=Decimal('1000.00'),
            reference_order=order,
        )

        snapshot = self._build_snapshot(client=branch, debt_percentage=10)
        debt_card = self._snapshot_card(snapshot, 'Deuda actual')

        self.assertEqual(debt_card['value'], '$100.00')
        self.assertEqual(debt_card['note'], 'Pendiente')

    def test_snapshot_subtracts_inherited_branch_credit_payments(self) -> None:
        corporate = Client.objects.create(
            name='Corporativo con pagos',
            type='corporate',
            credit_limit=Decimal('1000.00'),
            current_debt=Decimal('60.00'),
            can_pay_with_credit=True,
        )
        branch = Client.objects.create(
            name='Sucursal con pagos',
            type='branch',
            corporate=corporate,
            credit_override_enabled=False,
            current_debt=Decimal('0.00'),
        )
        order = self._create_credit_order(client=branch, amount=Decimal('100.00'))
        CreditTransaction.objects.create(
            client=corporate,
            amount=Decimal('100.00'),
            transaction_type='purchase',
            debt_before=Decimal('0.00'),
            debt_after=Decimal('100.00'),
            credit_limit_before=Decimal('1000.00'),
            credit_limit_after=Decimal('1000.00'),
            reference_order=order,
        )
        CreditTransaction.objects.create(
            client=corporate,
            amount=Decimal('40.00'),
            transaction_type='payment',
            debt_before=Decimal('100.00'),
            debt_after=Decimal('60.00'),
            credit_limit_before=Decimal('1000.00'),
            credit_limit_after=Decimal('1000.00'),
            reference_order=order,
        )

        snapshot = self._build_snapshot(client=branch, debt_percentage=6)
        debt_card = self._snapshot_card(snapshot, 'Deuda actual')

        self.assertEqual(debt_card['value'], '$60.00')

    def test_snapshot_shows_corporate_ledger_total_for_inherited_branch_debts(
        self,
    ) -> None:
        corporate = Client.objects.create(
            name='Corporativo suma',
            type='corporate',
            credit_limit=Decimal('1000.00'),
            current_debt=Decimal('300.00'),
            can_pay_with_credit=True,
        )
        first_branch = Client.objects.create(
            name='Sucursal uno',
            type='branch',
            corporate=corporate,
            credit_override_enabled=False,
        )
        second_branch = Client.objects.create(
            name='Sucursal dos',
            type='branch',
            corporate=corporate,
            credit_override_enabled=False,
        )
        first_order = self._create_credit_order(
            client=first_branch,
            amount=Decimal('100.00'),
        )
        second_order = self._create_credit_order(
            client=second_branch,
            amount=Decimal('200.00'),
        )
        for order in (first_order, second_order):
            CreditTransaction.objects.create(
                client=corporate,
                amount=order.total_amount,
                transaction_type='purchase',
                debt_before=Decimal('0.00'),
                debt_after=order.total_amount,
                credit_limit_before=Decimal('1000.00'),
                credit_limit_after=Decimal('1000.00'),
                reference_order=order,
            )

        snapshot = self._build_snapshot(client=corporate, debt_percentage=30)
        debt_card = self._snapshot_card(snapshot, 'Deuda actual')
        branch_purchase_total = CreditTransaction.objects.filter(
            client=corporate,
            reference_order__client__in=[first_branch, second_branch],
            transaction_type='purchase',
        ).aggregate(total=Sum('amount'))['total']

        self.assertEqual(branch_purchase_total, Decimal('300.00'))
        self.assertEqual(debt_card['value'], '$300.00')

    def test_snapshot_summarizes_next_billing_and_pending_invoices(self) -> None:
        self.client_obj.requires_billing = True
        self.client_obj.save(update_fields=['requires_billing', 'updated_at'])
        billing_frequency = ClientBillingFrecuency.objects.create(
            client=self.client_obj,
            frequency='monthly',
            billing_date='specific_date',
            start_date=date(2026, 7, 1),
            specific_day=8,
            is_active=True,
        )
        ClientBillingFrecuency.objects.filter(pk=billing_frequency.pk).update(
            next_billing_date=date(2026, 7, 8),
        )
        billing_frequency.refresh_from_db()
        order = Order.objects.create(
            client=self.client_obj,
            status=OrderStatus.COMPLETED.value,
            total_amount=Decimal('150.00'),
        )
        invoice = Invoice.objects.create(
            client=self.client_obj,
            amount=Decimal('150.00'),
            identifier='SER-ACT',
            folio='FOL-ACT',
        )
        InvoiceOrderLink.objects.create(invoice=invoice, order=order)

        snapshot = self._build_snapshot(
            billing_frequency=billing_frequency,
            client_invoices=[invoice],
        )
        billing_card = next(
            card for card in snapshot['snapshot_cards'] if card['label'] == 'Facturación'
        )

        self.assertEqual(billing_card['value'], 'Próxima: 08/07/2026')
        self.assertEqual(billing_card['note'], '1 factura pendiente')
