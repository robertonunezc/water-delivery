from datetime import date, timedelta
from decimal import Decimal
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch, MagicMock

from django.contrib.auth import get_user_model
from django.http import HttpResponse
from django.urls import reverse
from django.utils import timezone

from tenant_client.test_utils import FastTenantTestCase

from clients.models import Address, BalanceTransaction, Client, CreditTransaction, InvoiceData
from clients.services import balance_service

User = get_user_model()
from core.models import Employee, Transport
from orders.models import Order, OrderProduct, OrderStatus
from orders import services
from payment.models import Payment
from product.models import Product, ProductClientPrice, ProductCategory
from routes.models import Route, RouteClient
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

    def test_update_order_updates_existing_order_product(self) -> None:
        """Test that update_order updates quantity when OrderProduct already exists."""
        ProductClientPrice.objects.create(
            product=self.product,
            client=self.client,
            price=20.00,
        )
        OrderProduct.objects.create(
            order=self.order,
            product=self.product,
            quantity=1,
            unit_price=Decimal("20.00"),
        )

        result = services.update_order(
            order=self.order,
            quantity=5,
            product=self.product,
            client=self.client,
        )

        self.assertEqual(result.total_amount, Decimal("100.00"))
        order_product = OrderProduct.objects.get(order=self.order, product=self.product)
        self.assertEqual(order_product.quantity, 5)

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

    def test_update_order_deletes_product_when_quantity_negative(self) -> None:
        """Test that update_order removes OrderProduct when quantity is negative."""
        ProductClientPrice.objects.create(
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

        result = services.update_order(
            order=self.order,
            quantity=-1,
            product=self.product,
            client=self.client,
        )

        self.assertEqual(result.total_amount, Decimal("0.00"))
        self.assertFalse(
            OrderProduct.objects.filter(order=self.order, product=self.product).exists()
        )

    def test_update_order_with_multiple_products(self) -> None:
        """Test that update_order correctly calculates total with multiple products."""
        product2 = Product.objects.create(
            name="Botella",
            presentation="1",
            unit_of_measure=1,
            category=self.category,
        )
        ProductClientPrice.objects.create(
            product=self.product,
            client=self.client,
            price=25.00,
        )
        ProductClientPrice.objects.create(
            product=product2,
            client=self.client,
            price=10.00,
        )

        services.update_order(
            order=self.order,
            quantity=2,
            product=self.product,
            client=self.client,
        )
        result = services.update_order(
            order=self.order,
            quantity=3,
            product=product2,
            client=self.client,
        )

        self.assertEqual(result.total_amount, Decimal("80.00"))

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


class UpdateOrderViewTestCase(FastTenantTestCase):
    """Integration tests for update_order endpoint behavior."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(username="order_user", password="testpass")
        self.client.force_login(self.user)

        self.customer = Client.objects.create(
            name="Client Endpoint",
            balance=Decimal("200.00"),
            credit_limit=Decimal("500.00"),
        )
        self.category = ProductCategory.objects.create(name="Water")
        self.product_1 = Product.objects.create(
            name="Garrafon",
            presentation="20",
            unit_of_measure=1,
            category=self.category,
            price=20.0,
        )
        self.product_2 = Product.objects.create(
            name="Botella",
            presentation="1",
            unit_of_measure=1,
            category=self.category,
            price=10.0,
        )

        ProductClientPrice.objects.create(
            product=self.product_1,
            client=self.customer,
            price=20.0,
        )
        ProductClientPrice.objects.create(
            product=self.product_2,
            client=self.customer,
            price=10.0,
        )

        self.order = Order.objects.create(
            client=self.customer,
            owner=self.user,
            status=OrderStatus.PENDING.value,
            discount=Decimal("0.00"),
            subtotal_amount=Decimal("0.00"),
            total_amount=Decimal("0.00"),
        )
        OrderProduct.objects.create(
            order=self.order,
            product=self.product_1,
            quantity=2,
            unit_price=Decimal("20.00"),
        )
        OrderProduct.objects.create(
            order=self.order,
            product=self.product_2,
            quantity=1,
            unit_price=Decimal("10.00"),
        )
        self.order.total_amount = services.calculate_order_total(self.order)
        self.order.save(update_fields=['subtotal_amount', 'total_amount'])

    def _post_update(self, payload: dict):
        return self.client.post(
            reverse('orders:update_order', kwargs={'order_pk': self.order.pk}),
            data=json.dumps(payload),
            content_type='application/json',
        )

    def test_update_endpoint_removes_product_and_recalculates_totals(self) -> None:
        response = self._post_update(
            {
                "quantity": 0,
                "product_id": str(self.product_1.pk),
                "discount": 0,
            }
        )

        self.assertEqual(response.status_code, 200)
        self.order.refresh_from_db()
        self.assertFalse(
            OrderProduct.objects.filter(order=self.order, product=self.product_1).exists()
        )
        self.assertEqual(self.order.subtotal_amount, Decimal("10.00"))
        self.assertEqual(self.order.total_amount, Decimal("10.00"))

    def test_update_endpoint_changes_quantity_and_discount(self) -> None:
        response = self._post_update(
            {
                "quantity": 3,
                "product_id": str(self.product_2.pk),
                "discount": "5.00",
            }
        )

        self.assertEqual(response.status_code, 200)
        self.order.refresh_from_db()
        item = OrderProduct.objects.get(order=self.order, product=self.product_2)
        self.assertEqual(item.quantity, 3)
        self.assertEqual(self.order.subtotal_amount, Decimal("70.00"))
        self.assertEqual(self.order.total_amount, Decimal("65.00"))

    def test_update_endpoint_discount_only_recalculates_total(self) -> None:
        response = self._post_update(
            {
                "quantity": 0,
                "discount": "12.00",
            }
        )

        self.assertEqual(response.status_code, 200)
        self.order.refresh_from_db()
        self.assertEqual(self.order.discount, Decimal("12.00"))
        self.assertEqual(self.order.subtotal_amount, Decimal("50.00"))
        self.assertEqual(self.order.total_amount, Decimal("38.00"))

    def test_update_endpoint_notes_only_keeps_existing_totals(self) -> None:
        response = self._post_update(
            {
                "notes": "Entregar antes de las 5 pm",
            }
        )

        self.assertEqual(response.status_code, 200)
        self.order.refresh_from_db()
        self.assertEqual(self.order.notes, "Entregar antes de las 5 pm")
        self.assertEqual(self.order.discount, Decimal("0.00"))
        self.assertEqual(self.order.subtotal_amount, Decimal("50.00"))
        self.assertEqual(self.order.total_amount, Decimal("50.00"))

    def test_update_endpoint_product_change_can_persist_notes(self) -> None:
        response = self._post_update(
            {
                "quantity": 3,
                "product_id": str(self.product_1.pk),
                "discount": "0.00",
                "notes": "Cliente solicita tocar el timbre",
            }
        )

        self.assertEqual(response.status_code, 200)
        self.order.refresh_from_db()
        self.assertEqual(self.order.notes, "Cliente solicita tocar el timbre")
        self.assertEqual(self.order.subtotal_amount, Decimal("70.00"))
        self.assertEqual(self.order.total_amount, Decimal("70.00"))


class CreateOrderRedirectTestCase(FastTenantTestCase):
    """Tests for route-aware redirects on the create order page."""

    def setUp(self) -> None:
        self.customer = Client.objects.create(name="Cliente Ruta")
        Address.objects.create(
            client=self.customer,
            type="delivery",
            street="Calle Ruta",
        )

    def _create_user_with_employee(self, *, username: str, position: str) -> User:
        user = User.objects.create_user(username=username, password="testpass")
        Employee.objects.create(
            user=user,
            nombre=username,
            apellidos="Prueba",
            curp=f"{username.upper():<18}"[:18],
            rfc=f"{username.upper():<13}"[:13],
            street_number="Calle 1",
            position=position,
        )
        return user

    def _create_route_assignment(
        self,
        *,
        name: str,
        weekday: str,
        anchor_date: date,
        sequence: int = 1,
    ) -> Route:
        transport = Transport.objects.create(
            license_plate=f"TEST-{sequence}",
            model="Unidad",
            capacity_liters=1000,
            is_active=True,
        )
        route = Route.objects.create(
            name=name,
            transportation=transport,
            weekday=weekday,
            is_active=True,
        )
        RouteClient.objects.create(
            route=route,
            client=self.customer,
            sequence=sequence,
            interval_weeks=1,
            anchor_date=anchor_date,
            is_active=True,
        )
        return route

    def _get_order_page_context(self) -> dict[str, Any]:
        with patch("orders.views.render") as render_mock:
            render_mock.side_effect = (
                lambda request, template_name, context: HttpResponse("ok")
            )
            response = self.client.get(
                reverse("orders:create_order", kwargs={"client_pk": self.customer.pk})
            )

        self.assertEqual(response.status_code, 200)
        render_mock.assert_called_once()
        return render_mock.call_args.args[2]

    def test_staff_order_page_redirects_to_clients_current_route(self) -> None:
        today = timezone.localdate()
        route = self._create_route_assignment(
            name="Ruta de Hoy",
            weekday=today.strftime("%A").lower(),
            anchor_date=today,
        )
        user = self._create_user_with_employee(username="ventas", position="staff")
        self.client.force_login(user)

        context = self._get_order_page_context()

        expected_url = reverse("routes:detail", kwargs={"route_id": route.pk})
        self.assertEqual(context["order_redirect_url"], expected_url)

    def test_driver_order_page_uses_today_route_when_client_has_multiple_routes(self) -> None:
        today = timezone.localdate()
        tomorrow = today + timedelta(days=1)
        tomorrow_weekday = tomorrow.strftime("%A").lower()
        today_route = self._create_route_assignment(
            name="Ruta Actual",
            weekday=today.strftime("%A").lower(),
            anchor_date=today,
            sequence=2,
        )
        self._create_route_assignment(
            name="Ruta Otro Dia",
            weekday=tomorrow_weekday,
            anchor_date=tomorrow,
            sequence=1,
        )
        user = self._create_user_with_employee(username="chofer", position="driver")
        self.client.force_login(user)

        context = self._get_order_page_context()

        self.assertEqual(
            context["order_redirect_url"],
            reverse("routes:detail", kwargs={"route_id": today_route.pk}),
        )

    def test_manager_order_page_keeps_clients_list_redirect(self) -> None:
        today = timezone.localdate()
        self._create_route_assignment(
            name="Ruta de Hoy",
            weekday=today.strftime("%A").lower(),
            anchor_date=today,
        )
        user = self._create_user_with_employee(username="manager", position="manager")
        self.client.force_login(user)

        context = self._get_order_page_context()

        self.assertEqual(context["order_redirect_url"], reverse("clients:list"))

    def test_order_template_wires_redirect_url_to_finish_buttons(self) -> None:
        template_path = Path(__file__).resolve().parent / "templates" / "create_order.html"
        template_source = template_path.read_text()

        self.assertEqual(template_source.count('data-redirect="{{ order_redirect_url }}"'), 2)


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

    def test_active_excludes_cancelled_orders(self) -> None:
        self.assertQuerySetEqual(
            Order.objects.active().order_by("id"),
            [self.active_order, self.review_order],
            transform=lambda order: order,
        )

    def test_cancelled_returns_only_cancelled_orders(self) -> None:
        self.assertQuerySetEqual(
            Order.objects.cancelled(),
            [self.cancelled_order],
            transform=lambda order: order,
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


class CancelOrderViewTestCase(FastTenantTestCase):
    """Integration tests for cancel_order endpoint behavior."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(username="cancel_view_user", password="testpass")
        self.client.force_login(self.user)
        self.customer = Client.objects.create(name="Cliente Cancelación Vista")
        self.category = ProductCategory.objects.create(name="Water View")
        self.product = Product.objects.create(
            name="Garrafón Vista",
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

    def test_cancel_order_endpoint_marks_order_cancelled(self) -> None:
        response = self.client.post(
            reverse('orders:cancel_order', kwargs={'order_pk': self.order.pk}),
            data=json.dumps({}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload.get('success'))
        self.assertIn('redirect_url', payload)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, OrderStatus.CANCELLED.value)

    def test_cancel_order_endpoint_allows_completed_order(self) -> None:
        self.order.status = OrderStatus.COMPLETED.value
        self.order.save(update_fields=['status'])

        response = self.client.post(
            reverse('orders:cancel_order', kwargs={'order_pk': self.order.pk}),
            data=json.dumps({}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload.get('success'))
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, OrderStatus.CANCELLED.value)

    def test_cancel_order_endpoint_returns_review_required_for_blocked_order(self) -> None:
        self.order.status = OrderStatus.COMPLETED.value
        self.order.save(update_fields=['status'])
        invoice = Invoice.objects.create(
            client=self.customer,
            amount=Decimal("50.00"),
            identifier="INV-CANCEL-VIEW-1",
            folio="F-CANCEL-VIEW-1",
        )
        InvoiceOrderLink.objects.create(invoice=invoice, order=self.order)

        response = self.client.post(
            reverse('orders:cancel_order', kwargs={'order_pk': self.order.pk}),
            data=json.dumps({}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertFalse(payload.get('success'))
        self.assertTrue(payload.get('review_required'))
        self.order.refresh_from_db()
        self.assertTrue(self.order.cancellation_review_required)


class OrdersDashboardBulkActionTestCase(FastTenantTestCase):
    """Tests for the dashboard bulk actions UI endpoint."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username="dashboard_user",
            password="testpass",
            is_staff=True,
        )
        self.client.force_login(self.user)

        self.customer = Client.objects.create(name="Bulk Client", type="corporate")
        self.other_customer = Client.objects.create(name="Other Bulk Client", type="corporate")
        self._make_invoice_ready(self.customer)
        self._make_invoice_ready(self.other_customer)

        self.completed_order_1 = Order.objects.create(
            client=self.customer,
            owner=self.user,
            status=OrderStatus.COMPLETED.value,
            total_amount=Decimal("50.00"),
        )
        self.completed_order_2 = Order.objects.create(
            client=self.customer,
            owner=self.user,
            status=OrderStatus.COMPLETED.value,
            total_amount=Decimal("30.00"),
        )
        self.pending_order = Order.objects.create(
            client=self.customer,
            owner=self.user,
            status=OrderStatus.PENDING.value,
            total_amount=Decimal("20.00"),
        )
        self.other_client_order = Order.objects.create(
            client=self.other_customer,
            owner=self.user,
            status=OrderStatus.COMPLETED.value,
            total_amount=Decimal("40.00"),
        )

    def _make_invoice_ready(self, client: Client) -> None:
        rfc_prefix = (client.name.upper().replace(' ', '') + 'XXXX')[:4]
        InvoiceData.objects.create(
            client=client,
            rfc=f'{rfc_prefix}010101AAA',
            razon_social=f'{client.name} SA de CV',
        )
        Address.objects.create(
            client=client,
            type='billing',
            street='Fiscal 123',
            locality='Centro',
            municipality='Queretaro',
            state='Queretaro',
            zip_code='76000',
            country='Mexico',
        )

    def test_dashboard_bulk_create_invoice_creates_invoice(self) -> None:
        response = self.client.post(
            reverse('admin_orders'),
            data={
                'bulk_action': 'create_invoice',
                'selected_orders': [self.completed_order_1.pk, self.completed_order_2.pk],
            },
        )

        self.assertEqual(response.status_code, 302)
        invoice = Invoice.objects.get(client=self.customer)
        self.assertEqual(invoice.amount, Decimal('80.00'))
        self.assertEqual(invoice.invoice_links.count(), 2)
        linked_order_ids = set(invoice.invoice_links.values_list('order_id', flat=True))
        self.assertSetEqual(
            linked_order_ids,
            {self.completed_order_1.id, self.completed_order_2.id},
        )

    def test_dashboard_bulk_create_invoice_rejects_non_completed_orders(self) -> None:
        response = self.client.post(
            reverse('admin_orders'),
            data={
                'bulk_action': 'create_invoice',
                'selected_orders': [self.completed_order_1.pk, self.pending_order.pk],
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Invoice.objects.exists())
        self.assertContains(response, 'Solo se pueden facturar pedidos completados')

    def test_dashboard_bulk_create_invoice_rejects_client_without_invoice_data(self) -> None:
        InvoiceData.objects.filter(client=self.customer).delete()

        response = self.client.post(
            reverse('admin_orders'),
            data={
                'bulk_action': 'create_invoice',
                'selected_orders': [self.completed_order_1.pk, self.completed_order_2.pk],
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Invoice.objects.exists())
        self.assertContains(response, 'no puede facturarse')
        self.assertContains(response, 'RFC')

    def test_dashboard_bulk_create_invoice_rejects_branch_when_corporate_lacks_billing_address(self) -> None:
        corporate = Client.objects.create(name='Corporate Client', type='corporate')
        self._make_invoice_ready(corporate)
        corporate.addresses.filter(type='billing').delete()

        branch = Client.objects.create(
            name='Branch Client',
            type='branch',
            corporate=corporate,
        )
        order = Order.objects.create(
            client=branch,
            owner=self.user,
            status=OrderStatus.COMPLETED.value,
            total_amount=Decimal('60.00'),
        )

        response = self.client.post(
            reverse('admin_orders'),
            data={'bulk_action': 'create_invoice', 'selected_orders': [order.pk]},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Invoice.objects.filter(client=branch).exists())
        self.assertContains(response, 'cliente corporativo')
        self.assertContains(response, 'domicilio de tipo fiscal activo')

    def test_dashboard_bulk_create_invoice_validates_corporate_for_branch_with_own_billing_data(self) -> None:
        corporate = Client.objects.create(name='Corporate Missing Billing', type='corporate')

        branch = Client.objects.create(
            name='Branch Own Billing Ignored',
            type='branch',
            corporate=corporate,
            credit_override_enabled=True,
        )
        self._make_invoice_ready(branch)
        order = Order.objects.create(
            client=branch,
            owner=self.user,
            status=OrderStatus.COMPLETED.value,
            total_amount=Decimal('45.00'),
        )

        response = self.client.post(
            reverse('admin_orders'),
            data={'bulk_action': 'create_invoice', 'selected_orders': [order.pk]},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Invoice.objects.filter(client=branch).exists())
        self.assertContains(response, 'cliente corporativo')
        self.assertContains(response, 'RFC')

    def test_dashboard_bulk_status_update_uses_service_layer(self) -> None:
        response = self.client.post(
            reverse('admin_orders'),
            data={
                'bulk_action': 'mark_pending',
                'selected_orders': [self.completed_order_1.pk],
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.completed_order_1.refresh_from_db()
        self.assertEqual(self.completed_order_1.status, OrderStatus.PENDING.value)

    def test_orders_list_shows_review_badge_for_blocked_cancellation(self) -> None:
        self.completed_order_1.cancellation_review_required = True
        self.completed_order_1.cancellation_review_reason = "Saldo insuficiente"
        self.completed_order_1.save(
            update_fields=[
                "cancellation_review_required",
                "cancellation_review_reason",
            ]
        )

        response = self.client.get(reverse("orders:list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Requiere revisión de cancelación")
        self.assertContains(response, "Saldo insuficiente")

    def test_admin_orders_list_shows_review_count_and_badge(self) -> None:
        self.completed_order_1.cancellation_review_required = True
        self.completed_order_1.cancellation_review_reason = "Saldo insuficiente"
        self.completed_order_1.save(
            update_fields=[
                "cancellation_review_required",
                "cancellation_review_reason",
            ]
        )

        response = self.client.get(reverse("admin_orders"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Cancelaciones por revisar")
        self.assertContains(response, "Requiere revisión de cancelación")

    def test_review_required_filter_returns_only_review_orders(self) -> None:
        self.completed_order_1.cancellation_review_required = True
        self.completed_order_1.cancellation_review_reason = "Saldo insuficiente"
        self.completed_order_1.save(
            update_fields=[
                "cancellation_review_required",
                "cancellation_review_reason",
            ]
        )

        response = self.client.get(reverse("admin_orders"), {"status": "REVIEW_REQUIRED"})

        self.assertEqual(response.status_code, 200)
        listed_orders = list(response.context["orders"].object_list)
        self.assertEqual(listed_orders, [self.completed_order_1])

class CalculateOrderTotalTestCase(FastTenantTestCase):
    """Tests for the calculate_order_total service function."""

    def setUp(self) -> None:
        self.client = Client.objects.create(name="Test Client")
        self.category = ProductCategory.objects.create(name="Water")
        self.product1 = Product.objects.create(
            name="Garrafon",
            presentation="20",
            unit_of_measure=1,
            category=self.category,
        )
        self.product2 = Product.objects.create(
            name="Botella",
            presentation="1",
            unit_of_measure=1,
            category=self.category,
        )
        self.order = Order.objects.create(
            client=self.client,
            total_amount=Decimal("0.00"),
        )

    def test_calculate_order_total_empty_order(self) -> None:
        """Test that calculate_order_total returns 0 for empty order."""
        total = services.calculate_order_total(self.order)
        self.assertEqual(total, Decimal("0.00"))

    def test_calculate_order_total_single_item(self) -> None:
        """Test calculate_order_total with a single item."""
        OrderProduct.objects.create(
            order=self.order,
            product=self.product1,
            quantity=3,
            unit_price=Decimal("25.00"),
        )

        total = services.calculate_order_total(self.order)
        self.assertEqual(total, Decimal("75.00"))

    def test_calculate_order_total_multiple_items(self) -> None:
        """Test calculate_order_total with multiple items."""
        OrderProduct.objects.create(
            order=self.order,
            product=self.product1,
            quantity=2,
            unit_price=Decimal("25.00"),
        )
        OrderProduct.objects.create(
            order=self.order,
            product=self.product2,
            quantity=5,
            unit_price=Decimal("10.00"),
        )

        total = services.calculate_order_total(self.order)
        self.assertEqual(total, Decimal("100.00"))

    def test_calculate_order_total_with_decimal_prices(self) -> None:
        """Test calculate_order_total handles decimal prices correctly."""
        OrderProduct.objects.create(
            order=self.order,
            product=self.product1,
            quantity=3,
            unit_price=Decimal("15.50"),
        )

        total = services.calculate_order_total(self.order)
        self.assertEqual(total, Decimal("46.50"))


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


class OrderPaymentRoutingTestCase(FastTenantTestCase):
    """Tests for the active order payment route."""

    def test_pay_order_url_resolves_to_view_not_legacy_service(self) -> None:
        from django.urls import resolve, reverse
        from orders import views

        match = resolve(reverse("orders:create_payment_for_order", args=[1]))

        self.assertIs(match.func, views.create_payment_for_order)
        self.assertFalse(hasattr(services, "create_payment_for_order"))


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
