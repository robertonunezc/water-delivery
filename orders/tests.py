from decimal import Decimal
from unittest.mock import patch, MagicMock

from django.contrib.auth import get_user_model
from django.utils import timezone

from tenant_client.test_utils import FastTenantTestCase

from clients.models import BalanceTransaction, Client, CreditTransaction
from clients.services import balance_service

User = get_user_model()
from orders.models import Order, OrderProduct, OrderStatus
from orders import services
from payment.models import Payment
from product.models import Product, ProductClientPrice, ProductCategory
from invoice.models import Invoice, InvoiceOrderLink


class UpdateOrderTestCase(FastTenantTestCase):
    """Tests for the update_order service function."""

    def setUp(self) -> None:
        self.client = Client.objects.create(
            name="Test Client",
            balance=Decimal("100.00"),
            credit_limit=Decimal("500.00"),
        )
        self.category = ProductCategory.objects.create(name="Water")
        self.product = Product.objects.create(
            name="Garrafon",
            presentation="20",
            unit_of_measure=1,
            category=self.category,
        )
        self.order = Order.objects.create(
            client=self.client,
            total_amount=Decimal("0.00"),
        )

    def test_update_order_creates_order_product_with_client_price(self) -> None:
        """Test that update_order creates an OrderProduct with client-specific price."""
        ProductClientPrice.objects.create(
            product=self.product,
            client=self.client,
            price=25.00,
        )

        result = services.update_order(
            order=self.order,
            quantity=3,
            product=self.product,
            client=self.client,
        )

        self.assertEqual(result.total_amount, Decimal("75.00"))
        order_product = OrderProduct.objects.get(order=self.order, product=self.product)
        self.assertEqual(order_product.quantity, 3)
        self.assertEqual(order_product.unit_price, Decimal("25.00"))

    def test_update_order_uses_base_price_when_no_client_price(self) -> None:
        """Test that update_order uses base_price when no client-specific price exists."""
        self.product.base_price = 30.00
        self.product.save()

        result = services.update_order(
            order=self.order,
            quantity=2,
            product=self.product,
            client=self.client,
        )

        self.assertEqual(result.total_amount, Decimal("60.00"))
        order_product = OrderProduct.objects.get(order=self.order, product=self.product)
        self.assertEqual(order_product.unit_price, Decimal("30.00"))

    def test_update_order_deletes_product_when_quantity_zero(self) -> None:
        """Test that update_order removes OrderProduct when quantity is 0."""
        ProductClientPrice.objects.create(
            product=self.product,
            client=self.client,
            price=20.00,
        )
        OrderProduct.objects.create(
            order=self.order,
            product=self.product,
            quantity=3,
            unit_price=Decimal("20.00"),
        )
        self.order.total_amount = Decimal("60.00")
        self.order.save()

        result = services.update_order(
            order=self.order,
            quantity=0,
            product=self.product,
            client=self.client,
        )

        self.assertEqual(result.total_amount, Decimal("0.00"))
        self.assertFalse(
            OrderProduct.objects.filter(order=self.order, product=self.product).exists()
        )

    def test_update_order_with_discount(self) -> None:
        """Test that update_order applies discount correctly."""
        ProductClientPrice.objects.create(
            product=self.product,
            client=self.client,
            price=25.00,
        )

        result = services.update_order(
            order=self.order,
            quantity=4,
            product=self.product,
            client=self.client,
            discount=Decimal("10.00"),
        )

        self.assertEqual(result.total_amount, Decimal("90.00"))

    def test_get_or_create_order_refreshes_reused_pending_item_prices(self) -> None:
        """Reused pending orders should reflect current client-specific pricing."""
        client_price = ProductClientPrice.objects.create(
            product=self.product,
            client=self.client,
            price=20.00,
        )
        OrderProduct.objects.create(
            order=self.order,
            product=self.product,
            quantity=2,
            unit_price=Decimal("20.00"),
        )
        self.order.total_amount = services.calculate_order_total(self.order)
        self.order.save(update_fields=['subtotal_amount', 'total_amount'])

        client_price.price = 25.00
        client_price.save(update_fields=['price'])

        order_data = services.get_or_create_order(client=self.client)

        self.assertEqual(order_data.total_amount, Decimal("50.00"))
        order_product = OrderProduct.objects.get(order=self.order, product=self.product)
        self.assertEqual(order_product.unit_price, Decimal("25.00"))


class OrderCancellationQuerySetTestCase(FastTenantTestCase):
    """Tests for order cancellation query helpers."""

    def setUp(self) -> None:
        self.customer = Client.objects.create(name="Cliente Query Cancelacion")
        self.active_order = Order.objects.create(
            client=self.customer,
            status=OrderStatus.COMPLETED.value,
            total_amount=Decimal("10.00"),
        )
        self.cancelled_order = Order.objects.create(
            client=self.customer,
            status=OrderStatus.CANCELLED.value,
            total_amount=Decimal("20.00"),
        )
        self.review_order = Order.objects.create(
            client=self.customer,
            status=OrderStatus.COMPLETED.value,
            total_amount=Decimal("30.00"),
            cancellation_review_required=True,
            cancellation_review_reason="Saldo insuficiente",
        )

    def test_review_required_returns_orders_waiting_for_staff_review(self) -> None:
        self.assertQuerySetEqual(
            Order.objects.review_required(),
            [self.review_order],
            transform=lambda order: order,
        )


class OrderCancellationFinancialReversalTestCase(FastTenantTestCase):
    """Tests for financial reversal helpers used by order cancellation."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(username="cancel_finance_user")
        self.customer = Client.objects.create(
            name="Cliente Reversas",
            balance=Decimal("100.00"),
            credit_limit=Decimal("500.00"),
        )
        self.order = Order.objects.create(
            client=self.customer,
            status=OrderStatus.COMPLETED.value,
            total_amount=Decimal("50.00"),
        )

    def test_reverse_balance_payment_restores_client_balance(self) -> None:
        payment = Payment(
            amount=Decimal("40.00"),
            method="balance",
            client=self.customer,
            order=self.order,
            status="completed",
            balance_used=Decimal("40.00"),
            created_by=self.user,
        )
        payment.save(apply_accounting=False)
        self.customer.balance = Decimal("60.00")
        self.customer.save(update_fields=["balance"])

        tx = balance_service.reverse_balance_payment(payment=payment, user=self.user)

        self.customer.refresh_from_db()
        self.assertEqual(self.customer.balance, Decimal("100.00"))
        self.assertEqual(tx.transaction_type, "payment_reversal")
        self.assertEqual(tx.reference_payment, payment)

    def test_reverse_added_order_balance_deducts_client_balance(self) -> None:
        tx = balance_service.reverse_added_order_balance(
            client=self.customer,
            amount=Decimal("25.00"),
            user=self.user,
            reference_order=self.order,
        )

        self.customer.refresh_from_db()
        self.assertIsNotNone(tx)
        self.assertEqual(self.customer.balance, Decimal("75.00"))
        self.assertEqual(tx.transaction_type, "added_in_order_reversal")
        self.assertEqual(tx.reference_order, self.order)

    def test_reverse_credit_purchase_reduces_client_debt(self) -> None:
        self.customer.current_debt = Decimal("75.00")
        self.customer.save(update_fields=["current_debt"])

        tx = balance_service.reverse_credit_purchase(
            client=self.customer,
            amount=Decimal("75.00"),
            user=self.user,
            reference_order=self.order,
            reference_payment=None,
            notes="Reversa de prueba",
        )

        self.customer.refresh_from_db()
        self.assertEqual(self.customer.current_debt, Decimal("0.00"))
        self.assertEqual(tx.transaction_type, "purchase_reversal")
        self.assertEqual(tx.reference_order, self.order)

    def test_reverse_credit_payment_restores_client_debt(self) -> None:
        self.customer.current_debt = Decimal("10.00")
        self.customer.save(update_fields=["current_debt"])

        tx = balance_service.reverse_credit_payment(
            client=self.customer,
            amount=Decimal("35.00"),
            user=self.user,
            reference_order=self.order,
            reference_payment=None,
            notes="Reversa de pago de prueba",
        )

        self.customer.refresh_from_db()
        self.assertEqual(self.customer.current_debt, Decimal("45.00"))
        self.assertEqual(tx.transaction_type, "payment_reversal")
        self.assertEqual(tx.reference_order, self.order)


class CancelOrderServiceTestCase(FastTenantTestCase):
    """Tests for status-based order cancellation."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(username="cancel_service_user", password="testpass")
        self.customer = Client.objects.create(
            name="Cliente Cancelación Servicio",
            balance=Decimal("100.00"),
            credit_limit=Decimal("500.00"),
        )
        self.category = ProductCategory.objects.create(name="Water Service")
        self.product = Product.objects.create(
            name="Garrafón Servicio",
            presentation="20",
            unit_of_measure=1,
            category=self.category,
        )
        self.order = Order.objects.create(
            client=self.customer,
            owner=self.user,
            status=OrderStatus.PENDING.value,
            total_amount=Decimal("50.00"),
        )
        OrderProduct.objects.create(
            order=self.order,
            product=self.product,
            quantity=2,
            unit_price=Decimal("25.00"),
        )

    def test_cancel_pending_order_marks_cancelled_without_deleting_items(self) -> None:
        result = services.cancel_order(order=self.order, user=self.user)

        self.assertTrue(result["success"])
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, OrderStatus.CANCELLED.value)
        self.assertTrue(OrderProduct.objects.filter(order=self.order).exists())
        self.assertFalse(self.order.cancellation_review_required)

    def test_cancel_pending_order_wrapper_uses_status_cancellation(self) -> None:
        result = services.cancel_pending_order(order=self.order, user=self.user)

        self.assertTrue(result["success"])
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, OrderStatus.CANCELLED.value)
        self.assertTrue(Order.objects.filter(pk=self.order.pk).exists())

    def test_cancel_completed_external_payment_marks_payment_reversed(self) -> None:
        self.order.status = OrderStatus.COMPLETED.value
        self.order.save(update_fields=["status"])
        payment = Payment.objects.create(
            amount=Decimal("50.00"),
            method="cash",
            client=self.customer,
            order=self.order,
            status="completed",
            created_by=self.user,
        )

        result = services.cancel_order(order=self.order, user=self.user)

        self.assertTrue(result["success"])
        self.order.refresh_from_db()
        payment.refresh_from_db()
        self.assertEqual(self.order.status, OrderStatus.CANCELLED.value)
        self.assertEqual(payment.status, "reversed")

    def test_cancel_order_with_balance_payment_restores_client_balance(self) -> None:
        self.order.status = OrderStatus.COMPLETED.value
        self.order.save(update_fields=["status"])
        payment = Payment.objects.create(
            amount=Decimal("40.00"),
            method="balance",
            client=self.customer,
            order=self.order,
            status="completed",
            created_by=self.user,
        )
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.balance, Decimal("60.00"))

        result = services.cancel_order(order=self.order, user=self.user)

        self.assertTrue(result["success"])
        self.customer.refresh_from_db()
        payment.refresh_from_db()
        self.assertEqual(self.customer.balance, Decimal("100.00"))
        self.assertEqual(payment.status, "reversed")
        self.assertTrue(
            BalanceTransaction.objects.filter(
                reference_payment=payment,
                transaction_type="payment_reversal",
            ).exists()
        )

    def test_cancel_order_with_credit_purchase_reduces_client_debt(self) -> None:
        self.order.status = OrderStatus.COMPLETED.value
        self.order.type = "credito"
        self.order.save(update_fields=["status", "type"])
        pending_credit = Payment(
            amount=Decimal("50.00"),
            method="pending_credit",
            client=self.customer,
            order=self.order,
            status="pending",
            created_by=self.user,
        )
        pending_credit.save(apply_accounting=False)
        balance_service.add_debt(
            client=self.customer,
            amount=Decimal("50.00"),
            transaction_type="purchase",
            user=self.user,
            reference_order=self.order,
            reference_payment=pending_credit,
        )

        result = services.cancel_order(order=self.order, user=self.user)

        self.assertTrue(result["success"])
        self.customer.refresh_from_db()
        pending_credit.refresh_from_db()
        self.assertEqual(self.customer.current_debt, Decimal("0.00"))
        self.assertEqual(pending_credit.status, "reversed")
        self.assertTrue(
            CreditTransaction.objects.filter(
                reference_order=self.order,
                transaction_type="purchase_reversal",
            ).exists()
        )

    def test_cancel_branch_credit_order_without_override_reduces_corporate_debt(self) -> None:
        corporate = Client.objects.create(
            name="Corporativo reversa crédito",
            type="corporate",
            credit_limit=Decimal("1000.00"),
            current_debt=Decimal("0.00"),
            can_pay_with_credit=True,
        )
        branch = Client.objects.create(
            name="Sucursal reversa crédito",
            type="branch",
            corporate=corporate,
            credit_override_enabled=False,
        )
        order = Order.objects.create(
            client=branch,
            status=OrderStatus.COMPLETED.value,
            total_amount=Decimal("500.00"),
            type="credito",
        )
        pending_credit = Payment(
            amount=Decimal("500.00"),
            method="pending_credit",
            client=branch,
            order=order,
            status="pending",
            created_by=self.user,
        )
        pending_credit.save(apply_accounting=False)
        balance_service.add_debt(
            client=branch,
            amount=Decimal("500.00"),
            transaction_type="purchase",
            user=self.user,
            reference_order=order,
            reference_payment=pending_credit,
        )
        corporate.refresh_from_db()
        self.assertEqual(corporate.current_debt, Decimal("500.00"))

        result = services.cancel_order(order=order, user=self.user)

        self.assertTrue(result["success"])
        corporate.refresh_from_db()
        branch.refresh_from_db()
        pending_credit.refresh_from_db()
        self.assertEqual(corporate.current_debt, Decimal("0.00"))
        self.assertEqual(branch.current_debt, Decimal("0.00"))
        self.assertEqual(pending_credit.status, "reversed")
        self.assertTrue(
            CreditTransaction.objects.filter(
                client=corporate,
                reference_order=order,
                reference_payment=pending_credit,
                transaction_type="purchase_reversal",
            ).exists()
        )

    def test_cancel_settled_credit_order_reverses_payment_and_purchase(self) -> None:
        self.order.status = OrderStatus.COMPLETED.value
        self.order.type = "credito"
        self.order.save(update_fields=["status", "type"])
        pending_credit = Payment(
            amount=Decimal("50.00"),
            method="pending_credit",
            client=self.customer,
            order=self.order,
            status="completed",
            created_by=self.user,
        )
        pending_credit.save(apply_accounting=False)
        balance_service.add_debt(
            client=self.customer,
            amount=Decimal("50.00"),
            transaction_type="purchase",
            user=self.user,
            reference_order=self.order,
            reference_payment=pending_credit,
        )
        settlement_payment = Payment.objects.create(
            amount=Decimal("50.00"),
            method="cash",
            client=self.customer,
            order=self.order,
            status="completed",
            created_by=self.user,
        )
        balance_service.pay_debt(
            client=self.customer,
            amount=Decimal("50.00"),
            transaction_type="payment",
            user=self.user,
            reference_order=self.order,
            reference_payment=settlement_payment,
        )
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.current_debt, Decimal("0.00"))

        result = services.cancel_order(order=self.order, user=self.user)

        self.assertTrue(result["success"])
        self.customer.refresh_from_db()
        pending_credit.refresh_from_db()
        settlement_payment.refresh_from_db()
        self.assertEqual(self.customer.current_debt, Decimal("0.00"))
        self.assertEqual(pending_credit.status, "reversed")
        self.assertEqual(settlement_payment.status, "reversed")
        self.assertTrue(
            CreditTransaction.objects.filter(
                reference_payment=settlement_payment,
                transaction_type="payment_reversal",
            ).exists()
        )
        self.assertTrue(
            CreditTransaction.objects.filter(
                reference_payment=pending_credit,
                transaction_type="purchase_reversal",
            ).exists()
        )

    def test_cancel_order_with_spent_added_balance_marks_review_required(self) -> None:
        self.order.status = OrderStatus.COMPLETED.value
        self.order.cantidad_cobrada = Decimal("100.00")
        self.order.save(update_fields=["status", "cantidad_cobrada"])
        BalanceTransaction.objects.create(
            client=self.customer,
            transaction_type="added_in_order",
            amount=Decimal("50.00"),
            balance_before=Decimal("50.00"),
            balance_after=Decimal("100.00"),
            reference_order=self.order,
            created_by=self.user,
        )
        self.customer.balance = Decimal("0.00")
        self.customer.save(update_fields=["balance"])

        result = services.cancel_order(order=self.order, user=self.user)

        self.assertFalse(result["success"])
        self.assertTrue(result["review_required"])
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, OrderStatus.COMPLETED.value)
        self.assertTrue(self.order.cancellation_review_required)
        self.assertIn("saldo", self.order.cancellation_review_reason.lower())

    def test_cancel_order_linked_to_invoice_marks_review_required(self) -> None:
        self.order.status = OrderStatus.COMPLETED.value
        self.order.save(update_fields=["status"])
        invoice = Invoice.objects.create(
            client=self.customer,
            amount=Decimal("50.00"),
            identifier="INV-CANCEL-1",
            folio="F-CANCEL-1",
        )
        InvoiceOrderLink.objects.create(invoice=invoice, order=self.order)

        result = services.cancel_order(order=self.order, user=self.user)

        self.assertFalse(result["success"])
        self.assertTrue(result["review_required"])
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, OrderStatus.COMPLETED.value)
        self.assertTrue(self.order.cancellation_review_required)
        self.assertIn("factura", self.order.cancellation_review_reason.lower())

    def test_successful_retry_clears_cancellation_review_metadata(self) -> None:
        self.order.status = OrderStatus.COMPLETED.value
        self.order.cancellation_review_required = True
        self.order.cancellation_review_reason = "Saldo insuficiente"
        self.order.cancellation_requested_at = timezone.now()
        self.order.cancellation_requested_by = self.user
        self.order.save(
            update_fields=[
                "status",
                "cancellation_review_required",
                "cancellation_review_reason",
                "cancellation_requested_at",
                "cancellation_requested_by",
            ]
        )

        result = services.cancel_order(order=self.order, user=self.user)

        self.assertTrue(result["success"])
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, OrderStatus.CANCELLED.value)
        self.assertFalse(self.order.cancellation_review_required)
        self.assertIsNone(self.order.cancellation_review_reason)
        self.assertIsNone(self.order.cancellation_requested_at)
        self.assertIsNone(self.order.cancellation_requested_by)

    def test_cancel_order_is_idempotent_when_already_cancelled(self) -> None:
        self.order.status = OrderStatus.CANCELLED.value
        self.order.save(update_fields=["status"])

        result = services.cancel_order(order=self.order, user=self.user)

        self.assertTrue(result["success"])
        self.assertTrue(result["skipped"])
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, OrderStatus.CANCELLED.value)


class ProcessOrderPaymentTestCase(FastTenantTestCase):
    """Tests for the process_order_payment service function."""

    def setUp(self) -> None:
        self.client = Client.objects.create(
            name="Test Client",
            balance=Decimal("100.00"),
            credit_limit=Decimal("500.00"),
            current_debt=Decimal("0.00"),
            can_pay_with_credit=True,
        )
        self.order = Order.objects.create(
            client=self.client,
            total_amount=Decimal("50.00"),
        )

    @patch("clients.services.balance_service.deduct_balance")
    def test_process_order_payment_balance_only_success(
        self, mock_deduct_balance: MagicMock
    ) -> None:
        """Test payment using balance only when sufficient balance exists."""
        mock_deduct_balance.return_value = MagicMock()

        result = services.process_order_payment(
            client=self.client,
            order_amount=Decimal("50.00"),
            payment_method="balance",
            order=self.order,
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["balance_used"], Decimal("50.00"))
        self.assertEqual(result["credit_used"], Decimal("0"))
        mock_deduct_balance.assert_called_once()

    def test_process_order_payment_balance_only_insufficient(self) -> None:
        """Test payment fails when balance is insufficient and method is balance."""
        self.client.balance = Decimal("30.00")
        self.client.save()

        result = services.process_order_payment(
            client=self.client,
            order_amount=Decimal("50.00"),
            payment_method="balance",
            order=self.order,
        )

        self.assertFalse(result["success"])
        self.assertIn("Insufficient balance", result["error"])
        self.assertEqual(result["balance_used"], Decimal("0"))

    @patch("clients.services.balance_service.add_debt")
    def test_process_order_payment_credit_only_success(
        self, mock_add_debt: MagicMock
    ) -> None:
        """Test payment using credit only when sufficient credit exists."""
        mock_add_debt.return_value = MagicMock()

        result = services.process_order_payment(
            client=self.client,
            order_amount=Decimal("50.00"),
            payment_method="credit",
            order=self.order,
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["credit_used"], Decimal("50.00"))
        self.assertEqual(result["balance_used"], Decimal("0"))
        mock_add_debt.assert_called_once()

    def test_process_order_payment_branch_without_override_uses_corporate_credit(self) -> None:
        """Test inherited branch credit payments use corporate credit ledger."""
        corporate = Client.objects.create(
            name="Corporativo helper crédito",
            type="corporate",
            credit_limit=Decimal("1000.00"),
            current_debt=Decimal("0.00"),
            can_pay_with_credit=True,
        )
        branch = Client.objects.create(
            name="Sucursal helper crédito",
            type="branch",
            corporate=corporate,
            balance=Decimal("0.00"),
            credit_limit=Decimal("0.00"),
            current_debt=Decimal("0.00"),
            can_pay_with_credit=False,
            credit_override_enabled=False,
        )
        order = Order.objects.create(
            client=branch,
            total_amount=Decimal("500.00"),
        )

        result = services.process_order_payment(
            client=branch,
            order_amount=Decimal("500.00"),
            payment_method="credit",
            order=order,
        )

        self.assertTrue(result["success"])
        corporate.refresh_from_db()
        branch.refresh_from_db()
        self.assertEqual(corporate.current_debt, Decimal("500.00"))
        self.assertEqual(branch.current_debt, Decimal("0.00"))
        self.assertEqual(result["current_debt"], Decimal("500.00"))

    def test_process_order_payment_credit_only_insufficient(self) -> None:
        """Test payment fails when credit is insufficient and method is credit."""
        self.client.current_debt = Decimal("480.00")
        self.client.save()

        result = services.process_order_payment(
            client=self.client,
            order_amount=Decimal("50.00"),
            payment_method="credit",
            order=self.order,
        )

        self.assertFalse(result["success"])
        self.assertIn("Insufficient credit", result["error"])

    @patch("clients.services.balance_service.add_debt")
    def test_process_order_payment_credit_disabled_blocks_even_when_limit_available(
        self, mock_add_debt: MagicMock
    ) -> None:
        """Test emergency credit stop blocks credit even when limit is available."""
        mock_add_debt.return_value = MagicMock()
        self.client.can_pay_with_credit = False
        self.client.balance = Decimal("0.00")
        self.client.credit_limit = Decimal("100.00")
        self.client.current_debt = Decimal("0.00")
        self.client.save()

        result = services.process_order_payment(
            client=self.client,
            order_amount=Decimal("50.00"),
            payment_method="credit",
            order=self.order,
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "Cliente no puede pagar con credito")
        self.assertEqual(result["credit_used"], Decimal("0"))
        mock_add_debt.assert_not_called()

    def test_process_order_payment_credit_succeeds_without_note(self) -> None:
        """Test credit payments no longer require a note."""
        result = services.process_order_payment(
            client=self.client,
            order_amount=Decimal("50.00"),
            payment_method="credit",
            order=self.order,
            credit_note=None,
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["credit_used"], Decimal("50.00"))

    @patch("clients.services.balance_service.add_debt")
    def test_process_order_payment_credit_with_note(
        self, mock_add_debt: MagicMock
    ) -> None:
        """Test payment succeeds and preserves optional credit notes."""
        mock_add_debt.return_value = MagicMock()

        result = services.process_order_payment(
            client=self.client,
            order_amount=Decimal("50.00"),
            payment_method="credit",
            order=self.order,
            credit_note="Authorized by manager",
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["credit_used"], Decimal("50.00"))

    @patch("clients.services.balance_service.deduct_balance")
    def test_process_order_payment_auto_uses_balance_first(
        self, mock_deduct_balance: MagicMock
    ) -> None:
        """Test auto method uses balance first before credit."""
        mock_deduct_balance.return_value = MagicMock()

        result = services.process_order_payment(
            client=self.client,
            order_amount=Decimal("50.00"),
            payment_method="auto",
            order=self.order,
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["balance_used"], Decimal("50.00"))
        self.assertEqual(result["credit_used"], Decimal("0"))
        mock_deduct_balance.assert_called_once()

    @patch("clients.services.balance_service.add_debt")
    @patch("clients.services.balance_service.deduct_balance")
    def test_process_order_payment_auto_mixed_balance_and_credit(
        self, mock_deduct_balance: MagicMock, mock_add_debt: MagicMock
    ) -> None:
        """Test auto method uses balance first then credit for remainder."""
        self.client.balance = Decimal("30.00")
        self.client.save()
        mock_deduct_balance.return_value = MagicMock()
        mock_add_debt.return_value = MagicMock()

        result = services.process_order_payment(
            client=self.client,
            order_amount=Decimal("50.00"),
            payment_method="auto",
            order=self.order,
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["balance_used"], Decimal("30.00"))
        self.assertEqual(result["credit_used"], Decimal("20.00"))

    def test_process_order_payment_auto_insufficient_total_funds(self) -> None:
        """Test auto method fails when total funds are insufficient."""
        self.client.balance = Decimal("30.00")
        self.client.current_debt = Decimal("490.00")
        self.client.save()

        result = services.process_order_payment(
            client=self.client,
            order_amount=Decimal("50.00"),
            payment_method="auto",
            order=self.order,
        )

        self.assertFalse(result["success"])
        self.assertIn("Insufficient funds", result["error"])

    @patch("clients.services.balance_service.add_debt")
    @patch("clients.services.balance_service.deduct_balance")
    def test_process_order_payment_auto_blocks_credit_when_toggle_disabled(
        self, mock_deduct_balance: MagicMock, mock_add_debt: MagicMock
    ) -> None:
        """Test emergency credit stop blocks auto payments that need credit."""
        self.client.balance = Decimal("30.00")
        self.client.can_pay_with_credit = False
        self.client.credit_limit = Decimal("100.00")
        self.client.current_debt = Decimal("0.00")
        self.client.save()
        mock_deduct_balance.return_value = MagicMock()
        mock_add_debt.return_value = MagicMock()

        result = services.process_order_payment(
            client=self.client,
            order_amount=Decimal("50.00"),
            payment_method="auto",
            order=self.order,
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "Cliente no puede pagar con credito")
        self.assertEqual(result["balance_used"], Decimal("0"))
        self.assertEqual(result["credit_used"], Decimal("0"))
        mock_deduct_balance.assert_not_called()
        mock_add_debt.assert_not_called()


class SalesSnapshotServiceTests(FastTenantTestCase):
    def setUp(self) -> None:
        self.client = Client.objects.create(name="Dashboard Client")

    def _create_order(
        self,
        *,
        amount: Decimal,
        status: str,
        order_date,
        discount: Decimal = Decimal("0.00"),
    ) -> Order:
        order = Order.objects.create(
            client=self.client,
            total_amount=amount,
            subtotal_amount=amount + discount,
            discount=discount,
            status=status,
        )
        Order.objects.filter(pk=order.pk).update(order_date=order_date)
        order.refresh_from_db()
        return order

    def test_sales_snapshot_counts_only_completed_orders_in_range(self) -> None:
        from datetime import datetime
        from django.utils import timezone

        start_date = datetime(2026, 6, 1).date()
        end_date = datetime(2026, 6, 30).date()

        cash_order = self._create_order(
            amount=Decimal("100.00"),
            discount=Decimal("10.00"),
            status=OrderStatus.COMPLETED.value,
            order_date=timezone.make_aware(datetime(2026, 6, 5, 10, 0)),
        )
        transfer_order = self._create_order(
            amount=Decimal("50.00"),
            status=OrderStatus.COMPLETED.value,
            order_date=timezone.make_aware(datetime(2026, 6, 8, 11, 0)),
        )
        pending_order = self._create_order(
            amount=Decimal("75.00"),
            status=OrderStatus.PENDING.value,
            order_date=timezone.make_aware(datetime(2026, 6, 9, 12, 0)),
        )
        outside_order = self._create_order(
            amount=Decimal("200.00"),
            status=OrderStatus.COMPLETED.value,
            order_date=timezone.make_aware(datetime(2026, 7, 1, 9, 0)),
        )

        Payment.objects.create(
            client=self.client,
            order=cash_order,
            amount=Decimal("100.00"),
            method="cash",
            status="completed",
        )
        Payment.objects.create(
            client=self.client,
            order=transfer_order,
            amount=Decimal("50.00"),
            method="bank_transfer",
            status="completed",
        )
        Payment.objects.create(
            client=self.client,
            order=pending_order,
            amount=Decimal("75.00"),
            method="cash",
            status="completed",
        )
        Payment.objects.create(
            client=self.client,
            order=outside_order,
            amount=Decimal("200.00"),
            method="cash",
            status="completed",
        )

        snapshot = services.get_sales_snapshot(start_date=start_date, end_date=end_date)

        self.assertEqual(snapshot["total_orders"], 2)
        self.assertEqual(snapshot["total_amount"], Decimal("150.00"))
        self.assertEqual(snapshot["average_ticket"], Decimal("75.00"))
        self.assertEqual(snapshot["total_discount"], Decimal("10.00"))
        payment_totals = {
            item["method"]: item["total_amount"]
            for item in snapshot["payment_methods"]
        }
        self.assertEqual(payment_totals["cash"], Decimal("100.00"))
        self.assertEqual(payment_totals["bank_transfer"], Decimal("50.00"))
        self.assertNotIn("pending_credit", payment_totals)
