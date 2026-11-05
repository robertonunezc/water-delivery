from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.urls import reverse

from clients.models import Client
from clients.services.balance_service import add_debt
from invoice.models import Invoice, InvoiceOrderLink
from orders.models import Order
from payment.models import Payment
from tenant_client.test_utils import FastTenantTestCase


class CreditReportPaymentTests(FastTenantTestCase):
    def setUp(self) -> None:
        self.user = get_user_model().objects.create_user(username='credit-report-payment')
        self.client.force_login(self.user)
        self.account = Client.objects.create(
            name='Cuenta de crédito', type='corporate', credit_limit=Decimal('1000.00'),
        )
        self.branch = Client.objects.create(name='Sucursal', corporate=self.account)
        self.invoiced = self._credit_order(self.branch, self.account, '100.00')
        self.uninvoiced = self._credit_order(self.account, self.account, '35.00')
        self.other = self._credit_order(self.account, self.account, '15.00')
        invoice = Invoice.objects.create(
            client=self.account, amount=Decimal('100.00'), identifier='CRED', folio='1',
        )
        InvoiceOrderLink.objects.create(invoice=invoice, order=self.invoiced)

    def _credit_order(self, client: Client, account: Client, amount: str) -> Order:
        order = Order.objects.create(
            client=client, credit_account=account, total_amount=Decimal(amount),
            status='COMPLETED', type='credito',
        )
        pending = Payment.objects.create(
            client=client, order=order, amount=Decimal(amount),
            method='pending_credit', status='pending', created_by=self.user,
        )
        add_debt(
            client=account, amount=Decimal(amount), reference_order=order,
            reference_payment=pending, user=self.user,
        )
        return order

    def _payment_url(self, client: Client | None = None) -> str:
        return reverse('report:pay_credit_orders', args=[(client or self.account).pk])

    def _payment_data(self, *orders: Order, amount: str = '135.00') -> dict:
        return {
            'orders': [order.pk for order in orders], 'amount': amount,
            'payment_method': 'cash', 'payment_date': '2026-11-05',
        }

    def test_report_exposes_invoiced_and_uninvoiced_order_selection(self) -> None:
        response = self.client.get(reverse('report:client_credit_report', args=[self.account.pk]))

        self.assertContains(response, 'Pagar seleccionados')
        self.assertContains(response, 'credit-report-payment-form')
        for order in (self.invoiced, self.uninvoiced, self.other):
            self.assertContains(response, f'name="orders" value="{order.pk}"')
        self.assertContains(response, self._payment_url())

    def test_selected_orders_open_existing_confirmation_with_current_total(self) -> None:
        response = self.client.get(self._payment_url(), {
            'orders': [self.invoiced.pk, self.uninvoiced.pk, self.invoiced.pk],
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['selected_total'], Decimal('135.00'))
        self.assertEqual(len(response.context['selected_orders']), 2)
        self.assertContains(response, reverse('report:client_credit_report', args=[self.account.pk]))

    def test_confirmation_pays_only_selected_orders_and_returns_to_report(self) -> None:
        response = self.client.post(
            self._payment_url(), self._payment_data(self.invoiced, self.uninvoiced),
        )

        self.assertRedirects(response, reverse('report:client_credit_report', args=[self.account.pk]))
        self.account.refresh_from_db()
        self.assertEqual(self.account.current_debt, Decimal('15.00'))
        self.assertTrue(Payment.objects.filter(order=self.other, status='pending').exists())
        self.assertEqual(Payment.objects.filter(method='cash', status='completed').count(), 2)

    def test_foreign_credit_account_is_rejected_without_recording_payment(self) -> None:
        foreign = Client.objects.create(name='Otra cuenta', type='corporate', credit_limit=1000)
        foreign_order = self._credit_order(foreign, foreign, '10.00')

        response = self.client.post(
            self._payment_url(), self._payment_data(self.invoiced, foreign_order),
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(Payment.objects.filter(method='cash').exists())
        self.account.refresh_from_db()
        self.assertEqual(self.account.current_debt, Decimal('150.00'))

    def test_transferred_order_can_be_paid_from_its_current_credit_account(self) -> None:
        account = Client.objects.create(
            name='Sucursal responsable', corporate=self.account,
            credit_override_enabled=True, credit_limit=1000,
        )
        transferred = self._credit_order(self.account, account, '25.00')

        response = self.client.post(
            self._payment_url(account), self._payment_data(transferred, amount='25.00'),
        )

        self.assertEqual(response.status_code, 302)
        account.refresh_from_db()
        self.assertEqual(account.current_debt, Decimal('0.00'))
        self.assertTrue(Payment.objects.filter(order=transferred, method='cash').exists())

    def test_selection_is_revalidated_if_credit_account_changes_before_confirmation(self) -> None:
        self.client.get(self._payment_url(), {'orders': [self.invoiced.pk]})
        foreign = Client.objects.create(name='Nueva cuenta', type='corporate', credit_limit=1000)
        Order.objects.filter(pk=self.invoiced.pk).update(credit_account=foreign)

        response = self.client.post(
            self._payment_url(), self._payment_data(self.invoiced, amount='100.00'),
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(Payment.objects.filter(method='cash').exists())

    def test_balance_payment_uses_current_balance_after_taking_locks(self) -> None:
        from clients.services.credit_report_service import pay_credit_report_orders
        from payment.services import ClientOrderPaymentError

        self.account.balance = Decimal('200.00')
        Client.objects.filter(pk=self.account.pk).update(balance=Decimal('60.00'))

        with self.assertRaises(ClientOrderPaymentError):
            pay_credit_report_orders(
                client=self.account, order_ids=[self.invoiced.pk],
                payment_method='balance', amount=Decimal('100.00'),
                request_user=self.user, payment_date=date(2026, 11, 5),
            )
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('60.00'))
        self.assertEqual(self.account.current_debt, Decimal('150.00'))

    def test_overpayment_adds_to_current_balance_instead_of_stale_view_balance(self) -> None:
        from clients.services.credit_report_service import pay_credit_report_orders

        self.account.balance = Decimal('200.00')
        Client.objects.filter(pk=self.account.pk).update(balance=Decimal('40.00'))

        pay_credit_report_orders(
            client=self.account, order_ids=[self.invoiced.pk],
            payment_method='cash', amount=Decimal('110.00'),
            request_user=self.user, payment_date=date(2026, 11, 5),
        )

        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('50.00'))
