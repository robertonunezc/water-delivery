from datetime import date, datetime
from decimal import Decimal

from django.utils import timezone

from clients.models import Client, ClientCreditConfig, CreditTransaction
from clients.services.credit_report_service import (
    get_client_credit_report,
    get_global_credit_report,
)
from invoice.models import Invoice, InvoiceOrderLink
from orders.models import Order, OrderStatus
from payment.models import Payment
from tenant_client.test_utils import FastTenantTestCase


class CreditReportServiceTests(FastTenantTestCase):
    def _set_order_date(self, order: Order, order_date: date) -> None:
        value = datetime.combine(order_date, datetime.min.time())
        if timezone.is_aware(timezone.now()):
            value = timezone.make_aware(value)
        Order.objects.filter(pk=order.pk).update(order_date=value)
        order.refresh_from_db()

    def _create_credit_order(
        self,
        *,
        client: Client,
        amount: Decimal,
        order_date: date,
        status: str = OrderStatus.COMPLETED.value,
    ) -> Order:
        order = Order.objects.create(
            client=client,
            subtotal_amount=amount,
            total_amount=amount,
            status=status,
            type="credito",
        )
        self._set_order_date(order, order_date)
        CreditTransaction.objects.create(
            client=client,
            transaction_type="purchase",
            amount=amount,
            debt_before=Decimal("0.00"),
            debt_after=amount,
            credit_limit_after=client.credit_limit,
            reference_order=order,
        )
        return order

    def _create_credit_client(
        self,
        *,
        name: str,
        current_debt: Decimal,
        credit_limit: Decimal,
        payment_term_type: str = "monthly_cutoff",
    ) -> Client:
        client = Client.objects.create(
            name=name,
            current_debt=current_debt,
            credit_limit=credit_limit,
        )
        ClientCreditConfig.objects.create(
            client=client,
            payment_term_type=payment_term_type,
            cutoff_day="last_day",
            max_payment_days=30,
        )
        return client

    def test_global_rows_include_credit_columns_and_sort_by_overdue_then_current_debt(
        self,
    ) -> None:
        tempano = self._create_credit_client(
            name="Tempano",
            current_debt=Decimal("17000.00"),
            credit_limit=Decimal("20000.00"),
        )
        vigor = self._create_credit_client(
            name="Vigor",
            current_debt=Decimal("8300.00"),
            credit_limit=Decimal("10000.00"),
        )
        inactive = self._create_credit_client(
            name="Inactivo",
            current_debt=Decimal("999.00"),
            credit_limit=Decimal("1000.00"),
        )
        inactive.active = False
        inactive.save(update_fields=["active"])
        Client.objects.create(name="Sin credito")

        self._create_credit_order(
            client=tempano,
            amount=Decimal("9700.00"),
            order_date=date(2026, 4, 1),
        )
        self._create_credit_order(
            client=tempano,
            amount=Decimal("7300.00"),
            order_date=date(2026, 7, 1),
        )
        self._create_credit_order(
            client=vigor,
            amount=Decimal("8300.00"),
            order_date=date(2026, 7, 1),
        )

        rows = get_global_credit_report(as_of=date(2026, 7, 8)).rows

        self.assertEqual([row.client.name for row in rows], ["Tempano", "Vigor"])
        self.assertEqual(rows[0].current_credit, Decimal("17000.00"))
        self.assertEqual(rows[0].authorized_credit_line, Decimal("20000.00"))
        self.assertEqual(rows[0].available_credit, Decimal("3000.00"))
        self.assertEqual(rows[0].overdue_amount, Decimal("9700.00"))
        self.assertEqual(rows[1].overdue_amount, Decimal("0.00"))

    def test_client_report_splits_invoiced_and_uninvoiced_open_credit(self) -> None:
        client = self._create_credit_client(
            name="Tempano",
            current_debt=Decimal("14200.00"),
            credit_limit=Decimal("20000.00"),
        )
        billed_order_one = self._create_credit_order(
            client=client,
            amount=Decimal("5000.00"),
            order_date=date(2026, 4, 1),
        )
        billed_order_two = self._create_credit_order(
            client=client,
            amount=Decimal("4700.00"),
            order_date=date(2026, 4, 8),
        )
        uninvoiced_order = self._create_credit_order(
            client=client,
            amount=Decimal("4500.00"),
            order_date=date(2026, 7, 1),
        )
        invoice = Invoice.objects.create(
            client=client,
            amount=Decimal("9700.00"),
            identifier="AA",
            folio="1313",
            emmited_at=date(2026, 4, 30),
        )
        InvoiceOrderLink.objects.create(invoice=invoice, order=billed_order_one)
        InvoiceOrderLink.objects.create(invoice=invoice, order=billed_order_two)

        report = get_client_credit_report(client=client, as_of=date(2026, 7, 8))

        self.assertEqual(report.invoiced_credit_total, Decimal("9700.00"))
        self.assertEqual(report.uninvoiced_credit_total, Decimal("4500.00"))
        self.assertFalse(report.has_reconciliation_warning)
        self.assertEqual(len(report.invoice_items), 1)
        self.assertEqual(report.invoice_items[0].invoice, invoice)
        self.assertEqual(report.invoice_items[0].open_amount, Decimal("9700.00"))
        self.assertEqual(
            [item.order for item in report.uninvoiced_orders],
            [uninvoiced_order],
        )

    def test_invoice_due_uninvoiced_orders_are_not_overdue_until_invoice_emission(
        self,
    ) -> None:
        client = self._create_credit_client(
            name="Invoice Due",
            current_debt=Decimal("100.00"),
            credit_limit=Decimal("1000.00"),
            payment_term_type="invoice_due",
        )
        self._create_credit_order(
            client=client,
            amount=Decimal("100.00"),
            order_date=date(2026, 1, 1),
        )

        global_report = get_global_credit_report(as_of=date(2026, 7, 8))
        client_report = get_client_credit_report(client=client, as_of=date(2026, 7, 8))

        self.assertEqual(global_report.rows[0].overdue_amount, Decimal("0.00"))
        self.assertIsNone(client_report.uninvoiced_orders[0].due_date)
        self.assertFalse(client_report.uninvoiced_orders[0].is_overdue)

    def test_cancelled_orders_and_reversed_payments_do_not_inflate_open_credit(
        self,
    ) -> None:
        client = self._create_credit_client(
            name="Reconciled",
            current_debt=Decimal("100.00"),
            credit_limit=Decimal("500.00"),
        )
        active_order = self._create_credit_order(
            client=client,
            amount=Decimal("100.00"),
            order_date=date(2026, 4, 1),
        )
        self._create_credit_order(
            client=client,
            amount=Decimal("500.00"),
            order_date=date(2026, 4, 1),
            status=OrderStatus.CANCELLED.value,
        )
        Payment.objects.create(
            amount=Decimal("100.00"),
            method="cash",
            client=client,
            order=active_order,
            status="reversed",
        )

        report = get_client_credit_report(client=client, as_of=date(2026, 7, 8))

        self.assertEqual(report.open_credit_total, Decimal("100.00"))
        self.assertEqual(report.overdue_amount, Decimal("100.00"))
