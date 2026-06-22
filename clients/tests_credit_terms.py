from datetime import date
from types import SimpleNamespace

from django.test import SimpleTestCase

from clients.services.pending_payment_service import (
    _monthly_cutoff_date,
    get_order_credit_due_date,
)


class CreditPaymentTermDateTests(SimpleTestCase):
    def test_sale_after_cutoff_is_due_next_month(self) -> None:
        due_date = _monthly_cutoff_date(date(2026, 6, 21), '20')

        self.assertEqual(due_date, date(2026, 7, 20))

    def test_sale_on_cutoff_is_due_the_same_day(self) -> None:
        due_date = _monthly_cutoff_date(date(2026, 6, 20), '20')

        self.assertEqual(due_date, date(2026, 6, 20))

    def test_last_day_uses_actual_month_end(self) -> None:
        due_date = _monthly_cutoff_date(date(2027, 2, 10), 'last_day')

        self.assertEqual(due_date, date(2027, 2, 28))

    def test_numeric_cutoff_is_clamped_to_month_end(self) -> None:
        due_date = _monthly_cutoff_date(date(2027, 2, 10), '30')

        self.assertEqual(due_date, date(2027, 2, 28))

    def test_invoice_due_date_uses_invoice_emission_date(self) -> None:
        invoice = SimpleNamespace(emmited_at=date(2026, 6, 10))
        link = SimpleNamespace(invoice=invoice)
        order = SimpleNamespace(invoice_links=SimpleNamespace(all=lambda: [link]))
        config = SimpleNamespace(
            payment_term_type='invoice_due',
            max_payment_days=30,
        )

        due_date = get_order_credit_due_date(order, config)

        self.assertEqual(due_date, date(2026, 7, 10))

    def test_invoice_due_date_waits_for_invoice_emission(self) -> None:
        order = SimpleNamespace(invoice_links=SimpleNamespace(all=lambda: []))
        config = SimpleNamespace(
            payment_term_type='invoice_due',
            max_payment_days=30,
        )

        self.assertIsNone(get_order_credit_due_date(order, config))
