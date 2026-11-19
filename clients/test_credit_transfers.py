from datetime import date
from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.contrib.admin.sites import AdminSite
from django.test import RequestFactory
from django.core.management import call_command, CommandError
from django.urls import reverse

from clients.models import Client, ClientCreditConfig, CreditTransaction
from clients.forms import ClientAdminForm, ClientCoreForm
from clients.admin import ClientAdmin
from clients.services import balance_service
from clients.services.client_service import ClientUpdateData, update_client, initialize_branch_credit_from_corporate
from clients.services.credit_report_service import get_client_credit_report
from clients.services.credit_payment_service import get_open_credit_orders_for_credit_management
from clients.services.pending_payment_service import get_overdue_orders_for_client
from clients.services.credit_transfer_service import transfer_branch_credit
from orders.models import Order
from orders.services import cancel_order
from payment.models import Payment
from payment.services import settle_credit_order_payment
from invoice.models import Invoice, InvoiceOrderLink
from tenant_client.test_utils import FastTenantTestCase


class BranchCreditTransferTests(FastTenantTestCase):
    def setUp(self) -> None:
        self.user = get_user_model().objects.create_user(username="credit-transfer-user")
        self.corporate = Client.objects.create(
            name="ABC", type="corporate", credit_limit=Decimal("5000.00"),
        )
        self.branch = Client.objects.create(
            name="XYZ", type="branch", corporate=self.corporate,
            credit_limit=Decimal("5000.00"),
        )

    def _credit_order(self, amount: str, paid: str = "0.00") -> Order:
        order = Order.objects.create(
            client=self.branch, total_amount=Decimal(amount), type="credito",
        )
        pending = Payment(
            client=self.branch, order=order, amount=Decimal(amount) - Decimal(paid),
            method="pending_credit", status="pending", created_by=self.user,
        )
        pending.save(apply_accounting=False)
        balance_service.add_debt(
            self.branch, Decimal(amount), reference_order=order, reference_payment=pending,
        )
        if Decimal(paid):
            payment = Payment(
                client=self.branch, order=order, amount=Decimal(paid),
                method="cash", status="completed", created_by=self.user,
            )
            payment.save(apply_accounting=False)
            balance_service.pay_debt(
                self.branch, Decimal(paid), reference_order=order, reference_payment=payment,
            )
        return order

    def _enable_own_credit(self, limit: str = "4000.00") -> Client:
        return update_client(
            self.branch,
            ClientUpdateData(credit_override_enabled=True, credit_limit=Decimal(limit)),
            self.user,
        )

    def _core_form_data(self, limit: str = "4000.00") -> dict[str, str]:
        return {
            "name": self.branch.name, "type": "branch", "corporate": str(self.corporate.pk),
            "active": "on", "confirmation_delivery_method": "whatsapp",
            "credit_override_enabled": "on", "branch_credit_limit": limit,
        }

    def test_enabling_own_credit_moves_unpaid_debt_and_releases_corporate(self) -> None:
        order = Order.objects.create(
            client=self.branch, total_amount=Decimal("2000.00"), type="credito",
        )
        purchase = balance_service.add_debt(
            self.branch, Decimal("2000.00"), reference_order=order,
        )

        update_client(
            self.branch,
            ClientUpdateData(credit_override_enabled=True, credit_limit=Decimal("4000.00")),
            self.user,
        )

        self.corporate.refresh_from_db()
        self.branch.refresh_from_db()
        purchase.refresh_from_db()
        self.assertEqual(self.corporate.current_debt, Decimal("0.00"))
        self.assertEqual(self.corporate.get_available_credit(), Decimal("5000.00"))
        self.assertEqual(self.branch.current_debt, Decimal("2000.00"))
        self.assertEqual(self.branch.get_available_credit(), Decimal("2000.00"))
        self.assertEqual(purchase.client_id, self.corporate.pk)
        self.assertEqual(purchase.amount, Decimal("2000.00"))
        self.assertEqual(CreditTransaction.objects.filter(
            reference_order=order, transaction_type="purchase",
        ).count(), 1)

    def test_only_unpaid_remainder_moves_and_payment_history_is_preserved(self) -> None:
        order = self._credit_order("3000.00", paid="1000.00")
        payment = order.payments.get(method="cash")

        self._enable_own_credit()

        self.corporate.refresh_from_db()
        self.branch.refresh_from_db()
        payment.refresh_from_db()
        self.assertEqual(self.corporate.current_debt, Decimal("0.00"))
        self.assertEqual(self.branch.current_debt, Decimal("2000.00"))
        self.assertEqual(payment.amount, Decimal("1000.00"))
        self.assertEqual(payment.status, "completed")
        self.assertEqual(order.total_paid, Decimal("1000.00"))
        self.assertEqual(order.credit_transfers.get().amount, Decimal("2000.00"))
        for account in (self.corporate, self.branch):
            summary = account.credit_transactions.all().aggregate_summary()
            self.assertEqual(summary["total_purchases"] - summary["total_payments"], account.current_debt)

    def test_insufficient_limit_rejects_configuration_and_debt_transfer(self) -> None:
        order = self._credit_order("2000.00")

        with self.assertRaisesRegex(ValueError, "2000.00"):
            self._enable_own_credit("1500.00")

        self.corporate.refresh_from_db()
        self.branch.refresh_from_db()
        self.assertFalse(self.branch.credit_override_enabled)
        self.assertEqual(self.branch.credit_limit, Decimal("5000.00"))
        self.assertEqual(self.corporate.current_debt, Decimal("2000.00"))
        self.assertEqual(self.branch.current_debt, Decimal("0.00"))
        self.assertFalse(order.credit_transfers.exists())

    def test_disabling_own_credit_returns_unpaid_debt_to_corporate_once(self) -> None:
        order = self._credit_order("2000.00")
        self._enable_own_credit()

        for _ in range(2):
            update_client(self.branch, ClientUpdateData(credit_override_enabled=False), self.user)

        self.corporate.refresh_from_db()
        self.branch.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual(self.corporate.current_debt, Decimal("2000.00"))
        self.assertEqual(self.branch.current_debt, Decimal("0.00"))
        self.assertEqual(order.get_credit_account().pk, self.corporate.pk)
        self.assertEqual(order.credit_transfers.count(), 2)

    def test_reverse_switch_rejects_insufficient_corporate_capacity(self) -> None:
        order = self._credit_order("2000.00")
        self._enable_own_credit()
        balance_service.add_debt(self.corporate, Decimal("4000.00"))

        with self.assertRaisesRegex(ValueError, "6000.00"):
            update_client(self.branch, ClientUpdateData(credit_override_enabled=False), self.user)

        self.corporate.refresh_from_db()
        self.branch.refresh_from_db()
        self.assertTrue(self.branch.credit_override_enabled)
        self.assertEqual(self.branch.current_debt, Decimal("2000.00"))
        self.assertEqual(self.corporate.current_debt, Decimal("4000.00"))
        self.assertEqual(order.credit_transfers.count(), 1)

    def test_settlement_after_transfer_reduces_branch_debt(self) -> None:
        order = self._credit_order("2000.00")
        self._enable_own_credit()

        payment, error = settle_credit_order_payment(
            order=order, payment_method="cash", amount=Decimal("2000.00"),
            request_user=self.user,
        )

        self.assertIsNone(error)
        self.corporate.refresh_from_db()
        self.branch.refresh_from_db()
        self.assertEqual(self.corporate.current_debt, Decimal("0.00"))
        self.assertEqual(self.branch.current_debt, Decimal("0.00"))
        self.assertEqual(CreditTransaction.objects.get(reference_payment=payment).client_id, self.branch.pk)

    def test_reports_count_transferred_order_only_on_destination(self) -> None:
        self._credit_order("2000.00")
        self._enable_own_credit()
        self.corporate.refresh_from_db()
        self.branch.refresh_from_db()

        corporate_report = get_client_credit_report(client=self.corporate)
        branch_report = get_client_credit_report(client=self.branch)

        self.assertEqual(corporate_report.open_credit_total, Decimal("0.00"))
        self.assertFalse(corporate_report.has_reconciliation_warning)
        self.assertEqual(branch_report.open_credit_total, Decimal("2000.00"))
        self.assertFalse(branch_report.has_reconciliation_warning)

    def test_cancelling_partially_paid_transferred_order_clears_each_ledger(self) -> None:
        order = self._credit_order("3000.00", paid="1000.00")
        self._enable_own_credit()

        result = cancel_order(order=order, user=self.user)

        self.assertTrue(result["success"], result)
        self.corporate.refresh_from_db()
        self.branch.refresh_from_db()
        self.assertEqual(self.corporate.current_debt, Decimal("0.00"))
        self.assertEqual(self.branch.current_debt, Decimal("0.00"))
        for account in (self.corporate, self.branch):
            summary = account.credit_transactions.all().aggregate_summary()
            self.assertEqual(summary["total_purchases"] - summary["total_payments"], Decimal("0.00"))

    def test_transferred_order_keeps_original_credit_terms(self) -> None:
        ClientCreditConfig.objects.create(
            client=self.corporate, payment_term_type="monthly_cutoff", cutoff_day="10",
        )
        ClientCreditConfig.objects.create(
            client=self.branch, payment_term_type="monthly_cutoff", cutoff_day="25",
        )
        order = self._credit_order("2000.00")
        Order.objects.filter(pk=order.pk).update(order_date="2026-06-05T12:00:00Z")
        self._enable_own_credit()
        self.branch.refresh_from_db()

        overdue = get_overdue_orders_for_client(self.branch)

        self.assertEqual(overdue["nearest_due_date"], date(2026, 6, 10))

    def test_basic_form_enables_credit_and_transfers_debt_with_new_limit(self) -> None:
        self._credit_order("2000.00")
        form = ClientCoreForm(data=self._core_form_data(), instance=self.branch)
        self.assertTrue(form.is_valid(), form.errors)

        form.save()

        self.corporate.refresh_from_db()
        self.branch.refresh_from_db()
        self.assertEqual(self.corporate.current_debt, Decimal("0.00"))
        self.assertEqual(self.branch.current_debt, Decimal("2000.00"))
        self.assertEqual(self.branch.credit_limit, Decimal("4000.00"))

    def test_basic_form_rejects_switch_when_new_limit_is_below_unpaid_debt(self) -> None:
        self._credit_order("2000.00")
        form = ClientCoreForm(data=self._core_form_data("1500.00"), instance=self.branch)

        self.assertFalse(form.is_valid())
        self.corporate.refresh_from_db()
        self.branch.refresh_from_db()
        self.assertFalse(self.branch.credit_override_enabled)
        self.assertEqual(self.corporate.current_debt, Decimal("2000.00"))

    def test_django_admin_switch_uses_transfer_service(self) -> None:
        self._credit_order("2000.00")
        self.branch.credit_override_enabled = True
        self.branch.credit_limit = Decimal("4000.00")
        request = RequestFactory().post("/admin/clients/client/")
        request.user = self.user

        ClientAdmin(Client, AdminSite()).save_model(request, self.branch, form=None, change=True)

        self.corporate.refresh_from_db()
        self.branch.refresh_from_db()
        self.assertEqual(self.corporate.current_debt, Decimal("0.00"))
        self.assertEqual(self.branch.current_debt, Decimal("2000.00"))
        self.assertEqual(self.branch.credit_transfers_in.get().created_by, self.user)

    def test_destination_credit_management_lists_transferred_orders(self) -> None:
        order = self._credit_order("2000.00")
        self._enable_own_credit()
        self.branch.refresh_from_db()

        self.assertEqual(get_open_credit_orders_for_credit_management(self.branch), [order])

    def _existing_override_branch(self, limit: str = "4000.00") -> Order:
        order = self._credit_order("2000.00")
        Client.objects.filter(pk=self.branch.pk).update(
            credit_override_enabled=True, credit_limit=Decimal(limit),
        )
        self.branch.refresh_from_db()
        return order

    def test_existing_branch_migration_previews_without_changing_debt(self) -> None:
        order = self._existing_override_branch()
        output = StringIO()

        call_command(
            "transfer_branch_credit", schema=self.tenant.schema_name,
            branch_id=self.branch.pk, stdout=output,
        )

        self.assertIn("2000.00", output.getvalue())
        self.corporate.refresh_from_db()
        self.branch.refresh_from_db()
        self.assertEqual(self.corporate.current_debt, Decimal("2000.00"))
        self.assertEqual(self.branch.current_debt, Decimal("0.00"))
        self.assertFalse(order.credit_transfers.exists())

    def test_existing_branch_migration_applies_once(self) -> None:
        order = self._existing_override_branch()

        for _ in range(2):
            call_command(
                "transfer_branch_credit", schema=self.tenant.schema_name,
                branch_id=self.branch.pk, apply=True, stdout=StringIO(),
            )

        self.corporate.refresh_from_db()
        self.branch.refresh_from_db()
        self.assertEqual(self.corporate.current_debt, Decimal("0.00"))
        self.assertEqual(self.branch.current_debt, Decimal("2000.00"))
        self.assertEqual(order.credit_transfers.count(), 1)

    def test_existing_branch_migration_rejects_insufficient_limit(self) -> None:
        order = self._existing_override_branch("1500.00")

        with self.assertRaisesRegex(CommandError, "2000.00"):
            call_command(
                "transfer_branch_credit", schema=self.tenant.schema_name,
                branch_id=self.branch.pk, apply=True, stdout=StringIO(),
            )

        self.corporate.refresh_from_db()
        self.branch.refresh_from_db()
        self.assertEqual(self.corporate.current_debt, Decimal("2000.00"))
        self.assertEqual(self.branch.current_debt, Decimal("0.00"))
        self.assertFalse(order.credit_transfers.exists())

    def test_invoice_issued_after_transfer_uses_original_invoice_terms(self) -> None:
        self.corporate.requires_billing = True
        self.corporate.save(update_fields=["requires_billing"])
        ClientCreditConfig.objects.create(
            client=self.corporate, payment_term_type="invoice_due", max_payment_days=30,
        )
        ClientCreditConfig.objects.create(
            client=self.branch, payment_term_type="monthly_cutoff", cutoff_day="25",
        )
        order = self._credit_order("2000.00")
        self._enable_own_credit()
        self.branch.refresh_from_db()
        before_invoice = get_overdue_orders_for_client(self.branch)
        self.assertTrue(before_invoice["awaiting_invoice"])
        invoice = Invoice.objects.create(
            client=self.corporate, amount=Decimal("2000.00"),
            identifier="ABC", folio="TRANSFER", emmited_at=date(2026, 6, 1),
        )
        InvoiceOrderLink.objects.create(invoice=invoice, order=order)

        report = get_client_credit_report(client=self.branch, as_of=date(2026, 7, 2))

        self.assertEqual(report.invoice_items[0].due_date, date(2026, 7, 1))
        self.assertEqual(report.overdue_amount, Decimal("2000.00"))
        invoice.refresh_from_db()
        self.assertEqual(invoice.client_id, self.corporate.pk)

    def test_fully_paid_orders_keep_original_account_after_credit_switch(self) -> None:
        order = self._credit_order("2000.00")
        payment, error = settle_credit_order_payment(
            order=order, payment_method="cash", amount=Decimal("2000.00"),
            request_user=self.user,
        )
        self.assertIsNone(error)
        self._enable_own_credit()

        result = cancel_order(order, self.user)

        self.assertTrue(result["success"], result)
        self.assertFalse(order.credit_transfers.exists())
        self.assertTrue(CreditTransaction.objects.filter(
            client=self.corporate, reference_payment=payment, transaction_type="payment_reversal",
        ).exists())
        self.corporate.refresh_from_db()
        self.branch.refresh_from_db()
        self.assertEqual(self.corporate.current_debt, Decimal("0.00"))
        self.assertEqual(self.branch.current_debt, Decimal("0.00"))

    def test_basic_edit_records_the_user_responsible_for_the_transfer(self) -> None:
        order = self._credit_order("2000.00")
        self.user.is_superuser = True
        self.user.is_staff = True
        self.user.save(update_fields=["is_superuser", "is_staff"])
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("clients:edit_v2", args=[self.branch.pk]),
            {**self._core_form_data(), "section": "basic"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(order.credit_transfers.get().created_by, self.user)

    def test_transfer_respects_the_persisted_corporate_limit(self) -> None:
        self._credit_order("2000.00")
        self._enable_own_credit()
        self.branch.refresh_from_db()
        Client.objects.filter(pk=self.corporate.pk).update(credit_limit=Decimal("1000.00"))

        with self.assertRaisesRegex(ValueError, "2000.00"):
            transfer_branch_credit(self.branch, self.branch, self.corporate, self.user)

        self.corporate.refresh_from_db()
        self.branch.refresh_from_db()
        self.assertEqual(self.corporate.current_debt, Decimal("0.00"))
        self.assertEqual(self.branch.current_debt, Decimal("2000.00"))

    def test_unpaid_order_with_zero_ledger_balance_blocks_the_switch(self) -> None:
        order = self._credit_order("2000.00")
        balance_service.pay_debt(
            self.branch, Decimal("2000.00"), transaction_type="forgiveness", reference_order=order,
        )

        with self.assertRaisesRegex(ValueError, "conciliación"):
            self._enable_own_credit()

        self.branch.refresh_from_db()
        self.assertFalse(self.branch.credit_override_enabled)
        self.assertFalse(order.credit_transfers.exists())

    def test_new_branch_with_own_credit_keeps_its_explicit_limit(self) -> None:
        form = ClientCoreForm(data={**self._core_form_data(), "name": "New own-credit branch"})
        self.assertTrue(form.is_valid(), form.errors)

        branch = form.save()
        initialize_branch_credit_from_corporate(branch)

        branch.refresh_from_db()
        self.assertEqual(branch.credit_limit, Decimal("4000.00"))

    def test_basic_edit_preserves_a_concurrently_changed_inherited_limit(self) -> None:
        data = {**self._core_form_data("5000.00"), "name": "XYZ renamed"}
        data.pop("credit_override_enabled")
        form = ClientCoreForm(data=data, instance=self.branch)
        Client.objects.filter(pk__in=[self.branch.pk, self.corporate.pk]).update(
            credit_limit=Decimal("3000.00"),
        )
        self.assertTrue(form.is_valid(), form.errors)

        form.save()

        self.branch.refresh_from_db()
        self.assertEqual(self.branch.name, "XYZ renamed")
        self.assertEqual(self.branch.credit_limit, Decimal("3000.00"))

    def test_admin_form_rejects_editing_an_inherited_limit_without_switching(self) -> None:
        data = {**self._core_form_data(), "balance": "0.00", "current_debt": "0.00", "credit_limit": "1500.00"}
        data.pop("credit_override_enabled")
        form = ClientAdminForm(data=data, instance=self.branch)

        self.assertFalse(form.is_valid())
