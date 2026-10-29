from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command, CommandError
from django.urls import reverse
from django.utils import timezone

from clients.models import Client, CreditTransaction
from clients.services.credit_payment_service import (
    get_open_credit_orders_for_credit_management,
)
from clients.services.credit_reconciliation_service import (
    get_credit_reconciliation_summary,
)
from orders.models import Order, OrderProduct, OrderSplit, OrderStatus
from orders.services import cancel_order
from orders.services.order_split_service import OrderSplitError, split_order
from payment.services import PaymentRequestData, process_payment_request
from payment.services import pay_client_orders
from payment.models import Payment
from product.models import Product, ProductCategory
from tenant_client.test_utils import FastTenantTestCase


class CreditOrderSplitTests(FastTenantTestCase):
    def setUp(self) -> None:
        self.user = get_user_model().objects.create_user(username="split-credit-user")
        self.corporate = Client.objects.create(
            name="Corporativo", type="corporate", credit_limit=Decimal("5000.00"),
        )
        self.customer = Client.objects.create(
            name="Sucursal", corporate=self.corporate,
        )
        category = ProductCategory.objects.create(name="Agua")
        self.product = Product.objects.create(
            name="Garrafón", presentation="20", unit_of_measure=1, category=category,
        )
        self.order = self._create_credit_order(8)
        self.other_order = self._create_credit_order(13)
        self.client.force_login(self.user)

    def _create_credit_order(self, quantity: int) -> Order:
        total = Decimal("47.00") * quantity
        order = Order.objects.create(
            client=self.customer, total_amount=total, subtotal_amount=total,
        )
        OrderProduct.objects.create(
            order=order, product=self.product, quantity=quantity,
            unit_price=Decimal("47.00"),
        )
        result, status = process_payment_request(
            order, PaymentRequestData(order_type="credito"), self.user,
        )
        self.assertEqual(status, 200, result)
        order.refresh_from_db()
        return order

    def _split_order(self) -> Order:
        item = self.order.items.get()
        response = self.client.post(
            reverse("orders:split_order", args=[self.order.pk]),
            {f"quantity_{item.pk}": 6},
        )
        self.assertEqual(response.status_code, 302)
        self.order.refresh_from_db()
        return Order.objects.exclude(pk__in=[self.order.pk, self.other_order.pk]).get()

    def test_original_part_can_be_paid_for_its_reduced_total(self) -> None:
        child = self._split_order()
        response = self.client.post(
            reverse("clients:pay_selected_orders", args=[self.customer.pk]),
            {"orders": [self.order.pk], "amount": "94.00",
             "payment_method": "credit_card", "payment_date": timezone.localdate()},
        )
        self.assertEqual(
            response.status_code, 302,
            response.context["error_message"] if response.status_code == 200 else "",
        )
        self.corporate.refresh_from_db()
        self.assertEqual(self.corporate.current_debt, Decimal("893.00"))
        self.assertEqual(self.order.total_paid, Decimal("94.00"))
        self.assertEqual(child.total_paid, Decimal("0.00"))

    def test_pending_credit_is_distributed_between_both_parts(self) -> None:
        child = self._split_order()
        self.assertEqual(
            self.order.payments.get(method="pending_credit").amount,
            Decimal("94.00"),
        )
        self.assertEqual(
            child.payments.get(method="pending_credit").amount, Decimal("282.00"),
        )
        self.assertEqual(child.type, "credito")

    def test_split_keeps_credit_reconciliation_balanced(self) -> None:
        self._split_order()
        summary = get_credit_reconciliation_summary(self.customer)
        self.assertEqual(summary.ledger_debt, Decimal("987.00"))
        self.assertEqual(summary.open_credit_total, Decimal("987.00"))
        self.assertEqual(summary.open_order_count, 3)
        self.assertTrue(summary.is_balanced)

    def test_child_part_is_selectable_and_can_be_paid_independently(self) -> None:
        child = self._split_order()
        open_ids = {
            order.pk for order in get_open_credit_orders_for_credit_management(self.customer)
        }
        self.assertIn(child.pk, open_ids)
        pay_client_orders(
            self.customer, [child], "cash", Decimal("282.00"), self.user,
        )
        self.corporate.refresh_from_db()
        self.assertEqual(self.corporate.current_debt, Decimal("705.00"))
        self.assertEqual(self.order.total_paid, Decimal("0.00"))
        self.assertTrue(get_credit_reconciliation_summary(self.customer).is_balanced)

    def test_cancelling_original_part_only_reverses_its_remaining_credit(self) -> None:
        self._split_order()
        result = cancel_order(self.order, user=self.user)
        self.assertTrue(result["success"], result)
        self.corporate.refresh_from_db()
        self.assertEqual(self.corporate.current_debt, Decimal("893.00"))
        self.assertTrue(get_credit_reconciliation_summary(self.customer).is_balanced)

    def test_split_preserves_original_purchase_and_total_account_debt(self) -> None:
        purchase = CreditTransaction.objects.get(
            reference_order=self.order, transaction_type="purchase",
        )
        self._split_order()
        purchase.refresh_from_db()
        self.assertEqual(purchase.amount, Decimal("376.00"))
        self.assertEqual(purchase.debt_before, Decimal("0.00"))
        self.assertEqual(purchase.debt_after, Decimal("376.00"))
        self.corporate.refresh_from_db()
        self.assertEqual(self.corporate.current_debt, Decimal("987.00"))
        ledger = self.corporate.credit_transactions.all().aggregate_summary()
        self.assertEqual(
            ledger["total_purchases"] - ledger["total_payments"], Decimal("987.00"),
        )

    def test_prepaid_balance_is_not_charged_again_when_split_credit_is_paid(self) -> None:
        self.customer.balance = Decimal("100.00")
        self.customer.save(update_fields=["balance", "updated_at"])
        self.order = self._create_credit_order(8)
        item = self.order.items.get()
        response = self.client.post(
            reverse("orders:split_order", args=[self.order.pk]),
            {f"quantity_{item.pk}": 6},
        )
        self.assertEqual(response.status_code, 302)
        child = Order.objects.get(notes=f"Dividida de Orden #{self.order.pk}")
        self.assertEqual(self.order.total_paid, Decimal("25.00"))
        self.assertEqual(child.total_paid, Decimal("75.00"))
        pay_client_orders(self.customer, [child], "cash", Decimal("207.00"), self.user)
        self.customer.refresh_from_db()
        self.corporate.refresh_from_db()
        self.assertEqual(self.customer.balance, Decimal("0.00"))
        self.assertEqual(self.corporate.current_debt, Decimal("1056.00"))
        self.assertTrue(get_credit_reconciliation_summary(self.customer).is_balanced)

    def _legacy_split(self) -> Order:
        self.order.items.update(quantity=2)
        self.order.total_amount = Decimal("94.00")
        self.order.save(update_fields=["total_amount", "updated_at"])
        child = Order.objects.create(
            client=self.customer, status=OrderStatus.COMPLETED.value,
            total_amount=Decimal("282.00"),
        )
        OrderProduct.objects.create(
            order=child, product=self.product, quantity=6, unit_price=Decimal("47.00"),
        )
        OrderSplit.objects.create(source_order=self.order, child_order=child, split_by=self.user)
        return child

    def test_legacy_repair_dry_run_does_not_change_financial_records(self) -> None:
        child = self._legacy_split()
        count = CreditTransaction.objects.count()
        output = StringIO()
        call_command("repair_split_order_credit", order_id=self.order.pk, stdout=output)
        self.assertIn(f"order #{self.order.pk}: pending_credit=$94.00", output.getvalue())
        self.assertIn(f"order #{child.pk}: pending_credit=$282.00", output.getvalue())
        self.assertEqual(self.order.payments.get(method="pending_credit").amount, Decimal("376.00"))
        self.assertFalse(child.payments.exists())
        self.assertEqual(CreditTransaction.objects.count(), count)

    def test_legacy_repair_is_idempotent_and_allows_both_parts_to_be_paid(self) -> None:
        child = self._legacy_split()
        for _ in range(2):
            call_command(
                "repair_split_order_credit", order_id=self.order.pk, apply=True, stdout=StringIO(),
            )
        self.assertEqual(child.payments.filter(method="pending_credit").count(), 1)
        self.assertEqual(CreditTransaction.objects.count(), 4)
        self.assertTrue(get_credit_reconciliation_summary(self.customer).is_balanced)
        pay_client_orders(self.customer, [self.order], "cash", Decimal("94.00"), self.user)
        pay_client_orders(self.customer, [child], "cash", Decimal("282.00"), self.user)
        self.corporate.refresh_from_db()
        self.assertEqual(self.corporate.current_debt, Decimal("611.00"))
        self.assertTrue(get_credit_reconciliation_summary(self.customer).is_balanced)

    def test_legacy_repair_rejects_a_family_with_existing_real_payments(self) -> None:
        child = self._legacy_split()
        payment = Payment(
            client=self.customer, order=child, amount=Decimal("282.00"),
            method="cash", status="completed",
        )
        payment.save(apply_accounting=False)
        with self.assertRaises(CommandError):
            call_command(
                "repair_split_order_credit", order_id=self.order.pk, apply=True, stdout=StringIO(),
            )
        self.assertEqual(self.order.payments.get(method="pending_credit").amount, Decimal("376.00"))
        self.corporate.refresh_from_db()
        self.assertEqual(self.corporate.current_debt, Decimal("987.00"))

    def _cash_order_with_payments(self, amounts: list[str]) -> Order:
        order = Order.objects.create(
            client=self.customer, total_amount=Decimal("376.00"),
            status=OrderStatus.COMPLETED.value,
        )
        OrderProduct.objects.create(
            order=order, product=self.product, quantity=8, unit_price=Decimal("47.00"),
        )
        for amount in amounts:
            payment = Payment(
                client=self.customer, order=order, amount=Decimal(amount),
                method="cash", status="completed",
            )
            payment.save(apply_accounting=False)
        return order

    def test_rounding_multiple_payments_keeps_both_parts_fully_paid(self) -> None:
        order = self._cash_order_with_payments(["93.99", "93.99", "93.99", "94.03"])
        child = split_order(order, {order.items.get().pk: 2}, self.user)
        order.refresh_from_db()
        self.assertEqual(child.total_paid, Decimal("94.00"))
        self.assertEqual(order.total_paid, Decimal("282.00"))
        self.assertTrue(child.is_paid)
        self.assertTrue(order.is_paid)

    def test_rounding_multiple_payments_preserves_a_one_cent_credit(self) -> None:
        from clients.services import balance_service

        order = self._cash_order_with_payments(["93.98", "93.98", "93.98", "94.05"])
        order.type = "credito"
        order.save(update_fields=["type", "updated_at"])
        pending = Payment(
            client=self.customer, order=order, amount=Decimal("0.01"),
            method="pending_credit", status="pending",
        )
        pending.save(apply_accounting=False)
        balance_service.add_debt(
            self.customer, Decimal("0.01"), reference_order=order, reference_payment=pending,
        )
        child = split_order(order, {order.items.get().pk: 2}, self.user)
        self.assertEqual(child.total_paid, Decimal("94.00"))
        self.assertEqual(order.payments.get(method="pending_credit").amount, Decimal("0.01"))
        self.assertTrue(get_credit_reconciliation_summary(self.customer).is_balanced)

    def test_legacy_repair_rejects_credit_already_reduced_in_the_ledger(self) -> None:
        from clients.services import balance_service

        child = self._legacy_split()
        balance_service.reverse_credit_purchase(
            self.customer, Decimal("282.00"), reference_order=self.order,
        )
        with self.assertRaises(CommandError):
            call_command(
                "repair_split_order_credit", order_id=self.order.pk, apply=True, stdout=StringIO(),
            )
        self.assertFalse(child.payments.exists())
        self.assertEqual(self.order.payments.get(method="pending_credit").amount, Decimal("376.00"))
        self.corporate.refresh_from_db()
        self.assertEqual(self.corporate.current_debt, Decimal("705.00"))

    def test_zero_rounded_balance_payment_does_not_prevent_cancellation(self) -> None:
        self.customer.balance = Decimal("0.01")
        self.customer.save(update_fields=["balance", "updated_at"])
        order = self._create_credit_order(8)
        split_order(order, {order.items.get().pk: 6}, self.user)
        result = cancel_order(order, user=self.user)
        self.assertTrue(result["success"], result)
        self.corporate.refresh_from_db()
        self.assertEqual(self.corporate.current_debt, Decimal("1268.99"))

    def test_credit_validation_failure_rolls_back_the_entire_split(self) -> None:
        CreditTransaction.objects.filter(reference_order=self.order).delete()
        item = self.order.items.get()
        with self.assertRaises(OrderSplitError):
            split_order(self.order, {item.pk: 6}, self.user)
        self.order.refresh_from_db()
        item.refresh_from_db()
        self.assertEqual(self.order.total_amount, Decimal("376.00"))
        self.assertEqual(item.quantity, 8)
        self.assertEqual(Order.objects.count(), 2)
        self.assertFalse(OrderSplit.objects.exists())
        self.assertEqual(
            self.order.payments.get(method="pending_credit").amount, Decimal("376.00"),
        )

    def test_discount_and_sale_date_are_preserved_when_splitting(self) -> None:
        from datetime import timedelta

        order = self._cash_order_with_payments(["372.00"])
        order.discount = Decimal("4.00")
        order.total_amount = Decimal("372.00")
        order.cantidad_cobrada = Decimal("372.00")
        order.order_date = timezone.now() - timedelta(days=40)
        order.save()
        child = split_order(order, {order.items.get().pk: 6}, self.user)
        order.refresh_from_db()
        self.assertEqual(order.total_amount, Decimal("93.00"))
        self.assertEqual(child.total_amount, Decimal("279.00"))
        self.assertEqual(order.discount, Decimal("1.00"))
        self.assertEqual(child.discount, Decimal("3.00"))
        self.assertEqual(child.order_date, order.order_date)
        self.assertEqual(order.cantidad_cobrada, Decimal("93.00"))
        self.assertEqual(child.cantidad_cobrada, Decimal("279.00"))
        self.assertTrue(order.is_paid)
        self.assertTrue(child.is_paid)

    def test_unmoved_products_remain_in_the_original_total(self) -> None:
        order = self._cash_order_with_payments(["386.00"])
        item = order.items.get()
        untouched = OrderProduct.objects.create(
            order=order, product=self.product, quantity=1, unit_price=Decimal("10.00"),
        )
        order.total_amount = Decimal("386.00")
        order.save(update_fields=["total_amount", "updated_at"])
        child = split_order(order, {item.pk: 6, untouched.pk: 0}, self.user)
        order.refresh_from_db()
        self.assertEqual(order.total_amount, Decimal("104.00"))
        self.assertEqual(child.total_amount, Decimal("282.00"))
        self.assertEqual(order.items.count(), 2)
        self.assertTrue(order.is_paid)
        self.assertTrue(child.is_paid)
