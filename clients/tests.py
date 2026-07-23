import csv
import io
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
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


class CorporateBranchWorkspaceViewTests(FastTenantTestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username='corporate-branch-workspace-user',
            password='testpass123',
        )
        self.client.force_login(self.user)
        self.corporate = Client.objects.create(
            name='Corporativo Vista',
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
        self._set_payment_date(self.branch_a_payment, day=9)
        self._set_payment_date(self.pending_credit_payment, day=10)

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

    def test_corporate_detail_links_to_branch_workspace(self) -> None:
        response = self.client.get(reverse('clients:detail', args=[self.corporate.pk]))

        self.assertContains(
            response,
            reverse('clients:corporate_branches', args=[self.corporate.pk]),
        )
        self.assertContains(response, 'Ver sucursales / ventas')

    def test_branch_client_cannot_open_branch_workspace(self) -> None:
        response = self.client.get(
            reverse('clients:corporate_branches', args=[self.branch_a.pk])
        )

        self.assertEqual(response.status_code, 404)

    def test_branch_workspace_renders_selected_branch_orders(self) -> None:
        response = self.client.get(
            reverse('clients:corporate_branches', args=[self.corporate.pk]),
            {
                'branch': self.branch_a.pk,
                'tab': 'orders',
                'date_from': '2026-07-01',
                'date_to': '2026-07-31',
            },
        )

        self.assertContains(response, 'Sucursal A')
        self.assertContains(response, f'#{self.branch_a_completed.id}')
        self.assertContains(response, f'#{self.branch_a_pending.id}')
        self.assertContains(response, f'#{self.branch_a_cancelled.id}')
        self.assertNotContains(response, f'#{self.branch_a_outside_range.id}')
        self.assertNotContains(response, f'#{self.branch_b_completed.id}')

    def test_branch_workspace_payments_tab_excludes_pending_credit_placeholder(self) -> None:
        response = self.client.get(
            reverse('clients:corporate_branches', args=[self.corporate.pk]),
            {
                'branch': self.branch_a.pk,
                'tab': 'payments',
                'date_from': '2026-07-01',
                'date_to': '2026-07-31',
            },
        )

        self.assertContains(response, f'#{self.branch_a_payment.id}')
        self.assertNotContains(response, 'Crédito Pendiente')


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


class AddressInlineFormTests(FastTenantTestCase):
    """Tests for AddressInlineForm and its same_as_previous helper field."""

    def setUp(self) -> None:
        self.client_obj = Client.objects.create(
            name="Test Address Client",
            type="corporate",
            requires_billing=True,
            active=True,
        )

    def test_form_has_same_as_previous_field(self) -> None:
        """The inline form must expose the non-model boolean field."""
        form = AddressInlineForm()
        self.assertIn('same_as_previous', form.fields)

    def test_same_as_previous_is_not_required(self) -> None:
        """The checkbox must be optional."""
        field = AddressInlineForm().fields['same_as_previous']
        self.assertFalse(field.required)

    def test_same_as_previous_label(self) -> None:
        """The checkbox label must match the spec."""
        field = AddressInlineForm().fields['same_as_previous']
        self.assertEqual(field.label, "Misma dirección que la anterior")

    def test_form_valid_without_same_as_previous(self) -> None:
        """Submitting without the helper field must not cause validation errors."""
        data = {
            'client': self.client_obj.pk,
            'type': 'shipping',
            'street': 'Av. Test 1',
            'locality': 'Querétaro',
            'municipality': 'Querétaro',
            'state': 'Querétaro',
            'zip_code': '76000',
            'country': 'Mexico',
        }
        form = AddressInlineForm(data=data)
        self.assertTrue(form.is_valid(), form.errors)

    def test_billing_uniqueness_still_enforced(self) -> None:
        """Existing billing uniqueness via Address.clean() must remain intact."""
        Address.objects.create(
            client=self.client_obj,
            type='billing',
            street='Av. First 1',
            locality='Querétaro',
            municipality='Querétaro',
            state='Querétaro',
            zip_code='76000',
            country='Mexico',
        )
        duplicate = Address(
            client=self.client_obj,
            type='billing',
            street='Av. Second 2',
            locality='Querétaro',
            municipality='Querétaro',
            state='Querétaro',
            zip_code='76000',
            country='Mexico',
        )
        with self.assertRaises(ValidationError):
            duplicate.full_clean()


class ClientDetailOrderActionsTests(FastTenantTestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username='client-detail-user',
            password='testpass123',
        )
        self.customer = Client.objects.create(
            name='Cliente detalle',
            active=True,
        )
        self.client.force_login(self.user)

    def _create_order(self, *, minutes_old: int) -> Order:
        order = Order.objects.create(
            client=self.customer,
            status=OrderStatus.COMPLETED.value,
            total_amount=Decimal('100.00'),
        )
        created_at = timezone.now() - timedelta(minutes=minutes_old)
        Order.objects.filter(pk=order.pk).update(created_at=created_at)
        order.created_at = created_at
        return order

    def _create_overdue_credit_order(
        self,
        *,
        total: Decimal = Decimal('100.00'),
    ) -> Order:
        self.customer.requires_billing = True
        self.customer.can_pay_with_credit = True
        self.customer.credit_limit = Decimal('1000.00')
        self.customer.current_debt = total
        self.customer.save(
            update_fields=[
                'requires_billing',
                'can_pay_with_credit',
                'credit_limit',
                'current_debt',
                'updated_at',
            ],
        )
        ClientCreditConfig.objects.create(
            client=self.customer,
            payment_term_type='monthly_cutoff',
            cutoff_day='1',
        )
        order = Order.objects.create(
            client=self.customer,
            status=OrderStatus.COMPLETED.value,
            total_amount=total,
            type='credito',
        )
        Order.objects.filter(pk=order.pk).update(
            order_date=timezone.now() - timedelta(days=60),
        )
        CreditTransaction.objects.create(
            client=self.customer,
            amount=total,
            transaction_type='purchase',
            debt_before=Decimal('0.00'),
            debt_after=total,
            credit_limit_before=Decimal('1000.00'),
            credit_limit_after=Decimal('1000.00'),
            reference_order=order,
        )
        return Order.objects.get(pk=order.pk)

    def test_closed_order_still_shows_order_action_link(self) -> None:
        order = Order.objects.create(
            client=self.customer,
            status=OrderStatus.COMPLETED.value,
            total_amount=Decimal('100.00'),
        )
        Payment.objects.create(
            client=self.customer,
            order=order,
            amount=Decimal('100.00'),
            method='cash',
            status='completed',
            created_by=self.user,
        )

        response = self.client.get(reverse('clients:detail', args=[self.customer.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            f'href="{reverse("orders:get_order", args=[order.pk])}"',
        )

    def test_orders_table_is_paginated_with_latest_10_first(self) -> None:
        orders = [self._create_order(minutes_old=minutes) for minutes in range(12)]

        response = self.client.get(reverse('clients:detail', args=[self.customer.pk]))

        orders_page = response.context['orders']
        self.assertEqual(response.status_code, 200)
        self.assertEqual(orders_page.paginator.per_page, 10)
        self.assertEqual(len(orders_page.object_list), 10)
        self.assertEqual(orders_page.object_list[0], orders[0])
        self.assertNotIn(orders[10], orders_page.object_list)
        self.assertTrue(orders_page.has_next())

    def test_orders_table_second_page_shows_older_orders(self) -> None:
        orders = [self._create_order(minutes_old=minutes) for minutes in range(12)]

        response = self.client.get(
            reverse('clients:detail', args=[self.customer.pk]),
            {'orders_page': '2'},
        )

        orders_page = response.context['orders']
        self.assertEqual(orders_page.number, 2)
        self.assertEqual(list(orders_page.object_list), [orders[10], orders[11]])

    def test_payment_history_is_paginated_independently(self) -> None:
        orders = [self._create_order(minutes_old=minutes) for minutes in range(12)]
        payments = []
        for index, order in enumerate(orders):
            payment = Payment.objects.create(
                client=self.customer,
                order=order,
                amount=Decimal('100.00'),
                method='cash',
                status='completed',
                created_by=self.user,
            )
            payment_date = timezone.now() - timedelta(minutes=index)
            Payment.objects.filter(pk=payment.pk).update(date=payment_date)
            payments.append(payment)

        response = self.client.get(
            reverse('clients:detail', args=[self.customer.pk]),
            {'orders_page': '1', 'payments_page': '2'},
        )

        orders_page = response.context['orders']
        payments_page = response.context['all_payment_data']
        self.assertEqual(orders_page.number, 1)
        self.assertEqual(payments_page.number, 2)
        self.assertEqual(payments_page.paginator.per_page, 10)
        self.assertEqual(
            [payment_data['id'] for payment_data in payments_page.object_list],
            [payments[10].id, payments[11].id],
        )

    def test_detail_header_renders_addresses_in_right_column(self) -> None:
        Address.objects.create(
            client=self.customer,
            type='delivery',
            street='Calle Header 42',
            municipality='Querétaro',
            state='Querétaro',
            zip_code='76000',
            country='México',
            active=True,
        )

        response = self.client.get(reverse('clients:detail', args=[self.customer.pk]))

        self.assertContains(response, 'client-header-addresses')
        self.assertContains(response, 'Calle Header 42')

    def test_detail_lists_order_linked_invoices_for_billing_client(self) -> None:
        self.customer.requires_billing = True
        self.customer.save(update_fields=['requires_billing', 'updated_at'])
        order = Order.objects.create(
            client=self.customer,
            status=OrderStatus.COMPLETED.value,
            total_amount=Decimal('150.00'),
        )
        invoice = Invoice.objects.create(
            client=self.customer,
            amount=Decimal('150.00'),
            identifier='SER-CLIENT',
            folio='FOL-CLIENT',
            emmited_at=timezone.localdate(),
        )
        InvoiceOrderLink.objects.create(invoice=invoice, order=order)

        response = self.client.get(reverse('clients:detail', args=[self.customer.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertIn(invoice, list(response.context['client_invoices']))
        self.assertContains(response, 'Facturas')
        self.assertContains(response, 'SER-CLIENT')
        self.assertContains(response, 'FOL-CLIENT')
        self.assertContains(
            response,
            f'href="{reverse("admin_edit_invoice", args=[invoice.pk])}"',
        )

    def test_detail_hides_invoice_section_when_client_does_not_require_billing(self) -> None:
        order = Order.objects.create(
            client=self.customer,
            status=OrderStatus.COMPLETED.value,
            total_amount=Decimal('90.00'),
        )
        invoice = Invoice.objects.create(
            client=self.customer,
            amount=Decimal('90.00'),
            identifier='SER-HIDDEN',
            folio='FOL-HIDDEN',
        )
        InvoiceOrderLink.objects.create(invoice=invoice, order=order)

        response = self.client.get(reverse('clients:detail', args=[self.customer.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context['client_invoices']), [])
        self.assertNotContains(response, 'SER-HIDDEN')
        self.assertNotContains(response, 'Facturas')

    def test_branch_detail_lists_corporate_issued_invoice_linked_to_branch_order(self) -> None:
        corporate = Client.objects.create(
            name='Corporativo fiscal',
            type='corporate',
            requires_billing=True,
            active=True,
        )
        branch = Client.objects.create(
            name='Sucursal facturada',
            type='branch',
            corporate=corporate,
            requires_billing=True,
            active=True,
        )
        order = Order.objects.create(
            client=branch,
            status=OrderStatus.COMPLETED.value,
            total_amount=Decimal('210.00'),
        )
        invoice = Invoice.objects.create(
            client=corporate,
            amount=Decimal('210.00'),
            identifier='SER-CORP',
            folio='FOL-BRANCH',
            emmited_at=timezone.localdate(),
        )
        InvoiceOrderLink.objects.create(invoice=invoice, order=order)

        response = self.client.get(reverse('clients:detail', args=[branch.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertIn(invoice, list(response.context['client_invoices']))
        self.assertContains(response, 'SER-CORP')
        self.assertContains(response, 'Corporativo fiscal')

    def test_overdue_payments_table_links_invoiced_order_to_invoice(self) -> None:
        order = self._create_overdue_credit_order()
        invoice = Invoice.objects.create(
            client=self.customer,
            amount=Decimal('100.00'),
            identifier='SER-OVERDUE',
            folio='FOL-OVERDUE',
            emmited_at=timezone.localdate() - timedelta(days=45),
        )
        InvoiceOrderLink.objects.create(invoice=invoice, order=order)

        response = self.client.get(reverse('clients:detail', args=[self.customer.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '¡Atención! Pagos Vencidos')
        self.assertContains(response, '<th>Factura</th>')
        self.assertContains(
            response,
            f'href="{reverse("admin_edit_invoice", args=[invoice.pk])}"',
        )
        self.assertContains(response, f'#{invoice.pk}')

    def test_overdue_payments_table_shows_dash_for_order_without_invoice(self) -> None:
        self._create_overdue_credit_order()

        response = self.client.get(reverse('clients:detail', args=[self.customer.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '¡Atención! Pagos Vencidos')
        self.assertContains(response, '<th>Factura</th>')
        self.assertContains(response, '<span class="text-muted">-</span>')


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


class ClientSelectedOrderPaymentViewTests(FastTenantTestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username='selected-pay-view-user',
            password='testpass123',
        )
        self.customer = Client.objects.create(
            name='Cliente vista pagos',
            active=True,
        )
        self.client.force_login(self.user)

    def _order(self, total: Decimal) -> Order:
        return Order.objects.create(
            client=self.customer,
            status=OrderStatus.COMPLETED.value,
            total_amount=total,
        )

    def test_payment_page_prefills_selected_total(self) -> None:
        first = self._order(Decimal('100.00'))
        second = self._order(Decimal('80.00'))

        response = self.client.get(
            reverse('clients:pay_selected_orders', args=[self.customer.pk]),
            {'orders': [str(first.pk), str(second.pk)]},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['selected_total'], Decimal('180.00'))
        self.assertContains(response, 'value="180.00"')
        self.assertContains(response, f'#{first.pk}')
        self.assertContains(response, f'#{second.pk}')

    def test_payment_page_requires_selected_orders(self) -> None:
        response = self.client.get(
            reverse('clients:pay_selected_orders', args=[self.customer.pk]),
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('clients:detail', args=[self.customer.pk]))

    def test_payment_page_posts_payment_and_redirects_to_client_detail(self) -> None:
        first = self._order(Decimal('100.00'))
        second = self._order(Decimal('80.00'))

        response = self.client.post(
            reverse('clients:pay_selected_orders', args=[self.customer.pk]),
            {
                'orders': [str(first.pk), str(second.pk)],
                'amount': '180.00',
                'payment_method': 'cash',
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('clients:detail', args=[self.customer.pk]))
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertTrue(first.is_paid)
        self.assertTrue(second.is_paid)

    def test_payment_page_rejects_underpayment(self) -> None:
        first = self._order(Decimal('100.00'))

        response = self.client.post(
            reverse('clients:pay_selected_orders', args=[self.customer.pk]),
            {
                'orders': [str(first.pk)],
                'amount': '99.99',
                'payment_method': 'cash',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'menor al total seleccionado')
        self.assertFalse(Payment.objects.filter(order=first, method='cash').exists())


class ClientDetailSelectedPaymentUiTests(FastTenantTestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username='client-detail-pay-ui',
            password='testpass123',
        )
        self.customer = Client.objects.create(
            name='Cliente UI pagos',
            active=True,
            credit_limit=Decimal('1000.00'),
            can_pay_with_credit=True,
        )
        self.client.force_login(self.user)

    def test_recent_sales_unpaid_order_has_checkbox_and_pay_action(self) -> None:
        order = Order.objects.create(
            client=self.customer,
            status=OrderStatus.COMPLETED.value,
            total_amount=Decimal('100.00'),
        )

        response = self.client.get(reverse('clients:detail', args=[self.customer.pk]))

        pay_url = reverse('clients:pay_selected_orders', args=[self.customer.pk])
        self.assertContains(response, f'name="orders" value="{order.pk}"')
        self.assertContains(response, 'Pagar seleccionados')
        self.assertContains(response, f'href="{pay_url}?orders={order.pk}"')
        self.assertContains(response, 'Editar')

    def test_recent_sales_paid_order_has_no_payment_checkbox_or_pay_action(self) -> None:
        order = Order.objects.create(
            client=self.customer,
            status=OrderStatus.COMPLETED.value,
            total_amount=Decimal('100.00'),
        )
        Payment.objects.create(
            client=self.customer,
            order=order,
            amount=Decimal('100.00'),
            method='cash',
            status='completed',
            created_by=self.user,
        )

        response = self.client.get(reverse('clients:detail', args=[self.customer.pk]))

        self.assertNotContains(response, f'name="orders" value="{order.pk}"')
        self.assertNotContains(response, f'?orders={order.pk}"')

    def test_overdue_order_pay_action_points_to_selected_payment_page(self) -> None:
        ClientCreditConfig.objects.create(
            client=self.customer,
            payment_term_type='monthly_cutoff',
            cutoff_day='1',
        )
        self.customer.current_debt = Decimal('100.00')
        self.customer.save(update_fields=['current_debt', 'updated_at'])
        order = Order.objects.create(
            client=self.customer,
            status=OrderStatus.COMPLETED.value,
            total_amount=Decimal('100.00'),
            type='credito',
        )
        Order.objects.filter(pk=order.pk).update(
            order_date=timezone.now() - timedelta(days=60),
        )
        Payment.objects.create(
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
            created_by=self.user,
        )

        response = self.client.get(reverse('clients:detail', args=[self.customer.pk]))

        pay_url = reverse('clients:pay_selected_orders', args=[self.customer.pk])
        self.assertContains(response, '¡Atención! Pagos Vencidos')
        self.assertContains(response, f'name="orders" value="{order.pk}"')
        self.assertContains(response, f'href="{pay_url}?orders={order.pk}"')


class ClientDetailLayoutTests(FastTenantTestCase):
    def test_corporate_detail_lists_all_branches_with_status_badges(self) -> None:
        user = User.objects.create_user(
            username='client-detail-layout-user',
            password='testpass123',
        )
        corporate = Client.objects.create(
            name='Corporativo con sucursales',
            type='corporate',
            active=True,
        )
        active_branch = Client.objects.create(
            name='Sucursal activa',
            type='branch',
            corporate=corporate,
            active=True,
        )
        inactive_branch = Client.objects.create(
            name='Sucursal inactiva',
            type='branch',
            corporate=corporate,
            active=False,
        )
        self.client.force_login(user)

        response = self.client.get(reverse('clients:detail', args=[corporate.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Sucursales')
        self.assertContains(
            response,
            f'href="{reverse("clients:detail", args=[active_branch.pk])}"',
        )
        self.assertContains(
            response,
            f'href="{reverse("clients:detail", args=[inactive_branch.pk])}"',
        )
        self.assertContains(response, 'Sucursal activa')
        self.assertContains(response, 'Sucursal inactiva')
        self.assertContains(response, '<span class="badge bg-success">Activo</span>')
        self.assertContains(response, '<span class="badge bg-secondary">Inactivo</span>')


class ClientDetailSnapshotServiceTests(FastTenantTestCase):
    def setUp(self) -> None:
        self.client_obj = Client.objects.create(
            name='Cliente snapshot',
            active=True,
        )

    def _build_snapshot(
        self,
        *,
        billing_frequency: object | None = None,
        client_invoices: list[object] | None = None,
        pending_payment_data: dict[str, object] | None = None,
        debt_percentage: int = 0,
    ) -> dict[str, object]:
        return build_client_detail_snapshot(
            client=self.client_obj,
            billing_frequency=billing_frequency,
            route_clients=self.client_obj.client_routes.filter(is_active=True),
            upcoming_route_orders=[],
            client_invoices=client_invoices or [],
            pending_payment_data=pending_payment_data or {
                'total_overdue_amount': Decimal('0.00'),
            },
            debt_percentage=debt_percentage,
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

    def test_snapshot_keeps_route_card_stable_when_client_has_no_route(self) -> None:
        snapshot = self._build_snapshot()
        route_card = next(
            card for card in snapshot['snapshot_cards'] if card['label'] == 'Próxima visita'
        )

        self.assertEqual(route_card['value'], 'Sin ruta')
        self.assertEqual(route_card['note'], 'Sin ruta asignada')

    def test_snapshot_summarizes_credit_usage_when_credit_is_enabled(self) -> None:
        self.client_obj.credit_limit = Decimal('100.00')
        self.client_obj.current_debt = Decimal('20.00')
        self.client_obj.save(update_fields=['credit_limit', 'current_debt', 'updated_at'])

        snapshot = self._build_snapshot(debt_percentage=20)
        credit_card = next(
            card for card in snapshot['snapshot_cards'] if card['label'] == 'Crédito'
        )

        self.assertEqual(credit_card['value'], '20%')
        self.assertEqual(credit_card['note'], 'Disponible: $80.00 de $100.00')

    def test_snapshot_summarizes_next_billing_and_pending_invoices(self) -> None:
        self.client_obj.requires_billing = True
        self.client_obj.save(update_fields=['requires_billing', 'updated_at'])
        billing_frequency = ClientBillingFrecuency.objects.create(
            client=self.client_obj,
            frequency='monthly',
            billing_date='specific_date',
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


class ClientListModeTests(FastTenantTestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(username='client_mode_user', password='testpass123')
        self.client.login(username='client_mode_user', password='testpass123')

    def _create_client(self, *, name: str, debt: Decimal = Decimal('0.00')) -> Client:
        client = Client.objects.create(
            name=name,
            current_debt=debt,
            active=True,
        )
        Address.objects.create(
            client=client,
            type='delivery',
            street=f'Calle {name}',
            active=True,
        )
        return client

    def test_credits_mode_filters_clients_with_debt(self) -> None:
        debt_client = self._create_client(name='Cliente con deuda', debt=Decimal('150.00'))
        self._create_client(name='Cliente sin deuda')

        response = self.client.get(reverse('clients:list'), {'mode': 'credits'})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Créditos')
        self.assertContains(response, debt_client.name)
        self.assertContains(response, reverse('clients:pay_credit', kwargs={'pk': debt_client.pk}))
        self.assertNotContains(response, 'Cliente sin deuda')

    def test_outside_route_sales_mode_does_not_exclude_today_route_clients(self) -> None:
        route_client = self._create_client(name='Cliente en ruta')
        other_client = self._create_client(name='Cliente fuera de ruta')
        transport = Transport.objects.create(
            license_plate='OUT-001',
            model='Unidad venta',
            capacity_liters=1000,
            is_active=True,
        )
        today = date.today()
        route = Route.objects.create(
            name='Ruta de hoy',
            transportation=transport,
            weekday=today.strftime('%A').lower(),
            is_active=True,
        )
        RouteClient.objects.create(
            route=route,
            client=route_client,
            sequence=1,
            interval_weeks=1,
            anchor_date=today,
            is_active=True,
        )

        response = self.client.get(reverse('clients:list'), {'mode': 'outside_route_sales'})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Ventas fuera de ruta')
        self.assertContains(response, route_client.name)
        self.assertContains(response, other_client.name)

    def test_client_list_preserves_mode_in_search_and_pagination(self) -> None:
        for index in range(11):
            self._create_client(
                name=f'Credito paginado {index:02d}',
                debt=Decimal('25.00'),
            )

        response = self.client.get(
            reverse('clients:list'),
            {
                'mode': 'credits',
                'search': 'Credito paginado',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="mode" value="credits"')
        self.assertContains(response, 'mode=credits')
        self.assertContains(response, 'search=Credito+paginado')


class ClientRouteAssignmentTabTests(FastTenantTestCase):
    """Tests for managing RouteClient assignments from the client edit form."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username='route_tab_admin',
            password='testpass123',
            is_staff=True,
        )
        self.client.login(username='route_tab_admin', password='testpass123')
        self.client_obj = Client.objects.create(
            name='Route Tab Client',
            type='corporate',
            active=True,
        )
        self.transport = Transport.objects.create(
            license_plate='TAB-001',
            model='Route Tab Truck',
            capacity_liters=1000,
            is_active=True,
        )
        self.active_route = Route.objects.create(
            name='Active Client Tab Route',
            transportation=self.transport,
            weekday='monday',
            is_active=True,
        )
        self.inactive_route = Route.objects.create(
            name='Inactive Hidden Client Tab Route',
            transportation=self.transport,
            weekday='tuesday',
            is_active=False,
        )

    def _edit_url(self) -> str:
        return reverse('clients:edit_v2', kwargs={'pk': self.client_obj.pk})

    def _route_formset_post_data(self, route: Route) -> dict:
        return {
            'section': 'routes',
            'routes-TOTAL_FORMS': '1',
            'routes-INITIAL_FORMS': '0',
            'routes-MIN_NUM_FORMS': '0',
            'routes-MAX_NUM_FORMS': '1000',
            'routes-0-route': str(route.pk),
            'routes-0-sequence': '1',
            'routes-0-interval_weeks': '1',
            'routes-0-anchor_date': '2026-06-22',
            'routes-0-is_active': 'on',
            'routes-0-notes': 'Visita semanal',
        }

    def test_edit_form_renders_routes_tab(self) -> None:
        response = self.client.get(f'{self._edit_url()}?tab=routes')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Rutas')
        self.assertContains(response, 'Asignaciones de Ruta')
        self.assertContains(response, 'Fecha de inicio de ciclo')
        self.assertNotContains(response, 'Anchor date')

    def test_route_select_only_offers_active_routes_for_new_assignment(self) -> None:
        response = self.client.get(f'{self._edit_url()}?tab=routes')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.active_route.name)
        self.assertNotContains(response, self.inactive_route.name)

    def test_post_valid_route_assignment_creates_route_client(self) -> None:
        Address.objects.create(
            client=self.client_obj,
            type='delivery',
            street='Calle Ruta 1',
            active=True,
        )

        response = self.client.post(
            self._edit_url(),
            data=self._route_formset_post_data(self.active_route),
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            RouteClient.objects.filter(
                client=self.client_obj,
                route=self.active_route,
                is_active=True,
            ).exists()
        )

    def test_missing_delivery_address_keeps_user_on_routes_tab_with_errors(self) -> None:
        response = self.client.post(
            self._edit_url(),
            data=self._route_formset_post_data(self.active_route),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'dirección de envío válida')
        self.assertFalse(RouteClient.objects.filter(client=self.client_obj).exists())


class ClientCSVExternalIdTests(FastTenantTestCase):
    """Tests for CSV import/export support of client external_id."""

    def test_template_includes_external_id_header(self) -> None:
        template = get_clients_csv_template()
        header = template.splitlines()[0]
        self.assertIn("external_id", header)

    def test_import_sets_external_id(self) -> None:
        csv_content = (
            "client_name,external_id,type,corporate_name,active,note,address_street,"
            "address_exterior_number,address_interior_number,address_locality,address_municipality,"
            "address_state,address_zip_code,address_country,address_reference,contact_name,"
            "contact_phone,contact_email\n"
            "Cliente CSV,EXT-123,corporate,,true,nota,Av 1,10,,Centro,Queretaro,"
            "Queretaro,76000,Mexico,Referencia,Juan,5551234,juan@test.com\n"
        )

        summary = import_clients_from_csv(csv_content.encode("utf-8"))

        self.assertEqual(summary.created_clients, 1)
        client = Client.objects.get(name="Cliente CSV corporativo")
        self.assertEqual(client.external_id, "EXT-123")

    def test_export_includes_external_id_value(self) -> None:
        client = Client.objects.create(
            name="Cliente Export",
            type="corporate",
            active=True,
            external_id="ERP-900",
        )
        Address.objects.create(
            client=client,
            type="delivery",
            street="Calle Export 1",
            locality="Queretaro",
            municipality="Queretaro",
            state="Queretaro",
            zip_code="76000",
            country="Mexico",
            active=True,
        )

        exported = export_clients_to_csv([client])
        reader = csv.DictReader(io.StringIO(exported))
        rows = list(reader)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["external_id"], "ERP-900")


class ClientCSVCorporateNormalizationTests(FastTenantTestCase):
    def test_reuses_existing_corporate_without_suffix(self) -> None:
        existing = Client.objects.create(
            name="Michoacana",
            type="corporate",
            active=True,
        )

        corporate = _get_or_create_corporate("Michoacana")

        self.assertEqual(corporate.pk, existing.pk)
        corporate.refresh_from_db()
        self.assertEqual(corporate.name, "Michoacana corporativo")
        self.assertEqual(
            Client.objects.filter(
                type="corporate",
                name__in=["Michoacana", "Michoacana corporativo"],
            ).count(),
            1,
        )

    def test_import_uses_only_suffixed_corporate_name(self) -> None:
        csv_content = (
            "client_name,external_id,type,corporate_name,active,note,address_street,"
            "address_exterior_number,address_interior_number,address_locality,address_municipality,"
            "address_state,address_zip_code,address_country,address_reference,contact_name,"
            "contact_phone,contact_email\n"
            "BANANE,ERP-200,corporate,,true,,Av 10,10,,Centro,Queretaro,Queretaro,76000,Mexico,,,\n"
            "BANANE OLVERA,ERP-201,branch,BANANE,true,,Av 11,11,,Centro,Queretaro,Queretaro,76000,Mexico,,,\n"
        )

        summary = import_clients_from_csv(csv_content.encode("utf-8"))

        self.assertEqual(summary.errors, [])
        self.assertTrue(Client.objects.filter(name="BANANE OLVERA", type="branch").exists())
        self.assertTrue(Client.objects.filter(name="BANANE corporativo", type="corporate").exists())
        self.assertFalse(Client.objects.filter(name="BANANE", type="corporate").exists())
        self.assertEqual(Client.objects.filter(name__icontains="BANANE", type="corporate").count(), 1)
