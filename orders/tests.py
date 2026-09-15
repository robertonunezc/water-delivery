from datetime import date, timedelta
from decimal import Decimal
import json
from typing import Any
from unittest.mock import patch, MagicMock

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.http import HttpResponse
from django.test import RequestFactory, override_settings
from django.urls import reverse
from django.utils import timezone

from tenant_client.test_utils import FastTenantTestCase

from clients.models import Address, BalanceTransaction, Client, CreditTransaction, InvoiceData
from clients.services import balance_service

User = get_user_model()
from core.models import Employee, Transport
from orders.models import Order, OrderProduct, OrderStatus, OrderSplit
from orders import services
from orders.admin import OrderAdmin
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

    def test_update_endpoint_persists_submitted_order_date(self) -> None:
        original_time = timezone.localtime(self.order.order_date).time()

        response = self._post_update({"order_date": "2026-07-14"})

        self.assertEqual(response.status_code, 200)
        self.order.refresh_from_db()
        saved_order_date = timezone.localtime(self.order.order_date)
        self.assertEqual(saved_order_date.date(), date(2026, 7, 14))
        self.assertEqual(saved_order_date.time().replace(microsecond=0), original_time.replace(microsecond=0))

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

    def test_update_endpoint_rejects_completed_order_without_changes(self) -> None:
        self.order.status = OrderStatus.COMPLETED.value
        self.order.save(update_fields=['status', 'updated_at'])

        response = self._post_update(
            {
                "quantity": 3,
                "product_id": str(self.product_2.pk),
                "discount": "5.00",
                "notes": "Cambio no permitido",
            }
        )

        self.assertEqual(response.status_code, 403)
        data = response.json()
        self.assertEqual(data["status"], "error")
        self.assertEqual(
            data["error"],
            "El pedido esta terminado. Puede cancelarlo y crear uno nuevo en caso "
            "de algun error u otro escenario",
        )
        self.order.refresh_from_db()
        item = OrderProduct.objects.get(order=self.order, product=self.product_2)
        self.assertEqual(item.quantity, 1)
        self.assertEqual(self.order.discount, Decimal("0.00"))
        self.assertIsNone(self.order.notes)


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
            render_mock.side_effect = lambda request, _name, context: HttpResponse("ok")
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

    def test_order_page_allows_credit_as_selectable_payment_method_when_enabled(self) -> None:
        self.customer.credit_limit = Decimal("1000.00")
        self.customer.current_debt = Decimal("0.00")
        self.customer.can_pay_with_credit = True
        self.customer.save(
            update_fields=["credit_limit", "current_debt", "can_pay_with_credit"]
        )
        user = self._create_user_with_employee(username="cobranza", position="manager")
        self.client.force_login(user)

        context = self._get_order_page_context()

        self.assertIn(("credit", "Crédito"), context["payment_types"])

    def test_existing_completed_order_page_is_marked_not_editable(self) -> None:
        user = self._create_user_with_employee(username="cerrado", position="manager")
        self.client.force_login(user)
        order = Order.objects.create(
            client=self.customer,
            owner=user,
            status=OrderStatus.COMPLETED.value,
            total_amount=Decimal("25.00"),
        )

        with patch("orders.views.render") as render_mock:
            render_mock.side_effect = lambda request, _name, context: HttpResponse("ok")
            response = self.client.get(
                reverse("orders:get_order", kwargs={"order_id": order.pk})
            )

        self.assertEqual(response.status_code, 200)
        context = render_mock.call_args.args[2]
        self.assertFalse(context.get("order_is_editable", True))


class SplitOrderViewTestCase(FastTenantTestCase):
    """Integration tests for splitting orders."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(username="split_user", password="testpass")
        self.client.force_login(self.user)
        self.customer = Client.objects.create(name="Cliente Split")
        self.category = ProductCategory.objects.create(name="Water Split")
        self.product_1 = Product.objects.create(
            name="Garrafon Split",
            presentation="20",
            unit_of_measure=1,
            category=self.category,
            price=Decimal("20.00"),
        )
        self.product_2 = Product.objects.create(
            name="Botella Split",
            presentation="1",
            unit_of_measure=1,
            category=self.category,
            price=Decimal("10.00"),
        )
        self.order = Order.objects.create(
            client=self.customer,
            owner=self.user,
            status=OrderStatus.COMPLETED.value,
            subtotal_amount=Decimal("50.00"),
            total_amount=Decimal("50.00"),
        )
        self.item_1 = OrderProduct.objects.create(
            order=self.order,
            product=self.product_1,
            quantity=2,
            unit_price=Decimal("20.00"),
        )
        self.item_2 = OrderProduct.objects.create(
            order=self.order,
            product=self.product_2,
            quantity=1,
            unit_price=Decimal("10.00"),
        )

    def test_split_order_redirects_to_pedidos_list_after_success(self) -> None:
        response = self.client.post(
            reverse("orders:split_order", args=[self.order.pk]),
            {
                f"quantity_{self.item_1.pk}": "1",
                f"quantity_{self.item_2.pk}": "0",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("admin_orders"))
        self.assertTrue(OrderSplit.objects.filter(source_order=self.order).exists())


class OrderReceiptModelTests(FastTenantTestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(username="receipt-user", password="testpass")
        self.customer = Client.objects.create(name="Receipt Client")
        self.order = Order.objects.create(
            client=self.customer,
            owner=self.user,
            status=OrderStatus.COMPLETED.value,
            total_amount=Decimal("120.00"),
        )

    def test_order_receipt_is_one_to_one_with_order(self) -> None:
        from django.db import IntegrityError
        from orders.models import OrderReceipt, ReceiptDeliveryMethod

        OrderReceipt.objects.create(
            order=self.order,
            method=ReceiptDeliveryMethod.EMAIL,
            pdf_url="receipts/orders/1.pdf",
            contact_name="Ana Lopez",
            contact_email="ana@example.com",
            contact_phone="4421234567",
            contact_position="Compras",
            created_by=self.user,
        )

        with self.assertRaises(IntegrityError):
            OrderReceipt.objects.create(
                order=self.order,
                method=ReceiptDeliveryMethod.EMAIL,
                pdf_url="receipts/orders/1-copy.pdf",
                contact_name="Ana Lopez",
                contact_email="ana@example.com",
                created_by=self.user,
            )

    def test_order_receipt_defaults_to_unsent(self) -> None:
        from orders.models import OrderReceipt, ReceiptDeliveryMethod

        receipt = OrderReceipt.objects.create(
            order=self.order,
            method=ReceiptDeliveryMethod.EMAIL,
            pdf_url="receipts/orders/1.pdf",
            contact_name="Ana Lopez",
            contact_email="ana@example.com",
            created_by=self.user,
        )

        self.assertIsNone(receipt.sent_at)
        self.assertEqual(str(receipt), f"Recibo pedido #{self.order.pk} - email")


class ReceiptStorageServiceTests(FastTenantTestCase):
    @override_settings(
        RECEIPT_R2_ENDPOINT_URL="https://example-account.r2.cloudflarestorage.com",
        RECEIPT_R2_BUCKET_NAME="receipt-bucket",
        RECEIPT_R2_ACCESS_KEY_ID="access-key",
        RECEIPT_R2_SECRET_ACCESS_KEY="secret-key",
        RECEIPT_R2_OBJECT_PREFIX="receipts/test",
        RECEIPT_R2_SIGNED_URL_EXPIRES_SECONDS=900,
    )
    @patch("orders.services.receipt_storage_service.boto3.client")
    def test_upload_pdf_returns_private_object_key(self, client_mock: MagicMock) -> None:
        from orders.services.receipt_storage_service import CloudflareR2ReceiptStorage

        storage_client = client_mock.return_value
        storage = CloudflareR2ReceiptStorage.from_settings()

        key = storage.upload_pdf(order_id=42, pdf_bytes=b"%PDF-test")

        self.assertEqual(key, "receipts/test/orders/42/receipt.pdf")
        storage_client.put_object.assert_called_once_with(
            Bucket="receipt-bucket",
            Key="receipts/test/orders/42/receipt.pdf",
            Body=b"%PDF-test",
            ContentType="application/pdf",
        )

    @override_settings(
        RECEIPT_R2_ENDPOINT_URL="https://example-account.r2.cloudflarestorage.com",
        RECEIPT_R2_BUCKET_NAME="receipt-bucket",
        RECEIPT_R2_ACCESS_KEY_ID="access-key",
        RECEIPT_R2_SECRET_ACCESS_KEY="secret-key",
        RECEIPT_R2_OBJECT_PREFIX="receipts",
        RECEIPT_R2_SIGNED_URL_EXPIRES_SECONDS=600,
    )
    @patch("orders.services.receipt_storage_service.boto3.client")
    def test_download_pdf_reads_private_object(self, client_mock: MagicMock) -> None:
        from io import BytesIO
        from orders.services.receipt_storage_service import CloudflareR2ReceiptStorage

        storage_client = client_mock.return_value
        storage_client.get_object.return_value = {"Body": BytesIO(b"%PDF-private")}
        storage = CloudflareR2ReceiptStorage.from_settings()

        content = storage.download_pdf("receipts/orders/42/receipt.pdf")

        self.assertEqual(content, b"%PDF-private")
        storage_client.get_object.assert_called_once_with(
            Bucket="receipt-bucket",
            Key="receipts/orders/42/receipt.pdf",
        )

    @override_settings(
        RECEIPT_R2_ENDPOINT_URL="",
        RECEIPT_R2_BUCKET_NAME="",
        RECEIPT_R2_ACCESS_KEY_ID="",
        RECEIPT_R2_SECRET_ACCESS_KEY="",
    )
    def test_missing_r2_settings_raise_clear_error(self) -> None:
        from orders.services.receipt_storage_service import (
            CloudflareR2ReceiptStorage,
            ReceiptStorageError,
        )

        with self.assertRaisesMessage(ReceiptStorageError, "Cloudflare R2"):
            CloudflareR2ReceiptStorage.from_settings()


class ReceiptPdfServiceTests(FastTenantTestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(username="pdf-user", password="testpass")
        self.customer = Client.objects.create(name="PDF Client")
        self.category = ProductCategory.objects.create(name="Agua")
        self.product = Product.objects.create(
            name="Garrafon",
            presentation="20L",
            unit_of_measure=1,
            category=self.category,
            price=Decimal("30.00"),
        )
        self.order = Order.objects.create(
            client=self.customer,
            owner=self.user,
            status=OrderStatus.COMPLETED.value,
            subtotal_amount=Decimal("60.00"),
            discount=Decimal("5.00"),
            total_amount=Decimal("55.00"),
            cantidad_cobrada=Decimal("60.00"),
        )
        OrderProduct.objects.create(
            order=self.order,
            product=self.product,
            quantity=2,
            unit_price=Decimal("30.00"),
        )
        Payment.objects.create(
            client=self.customer,
            order=self.order,
            amount=Decimal("55.00"),
            method="cash",
            status="completed",
            created_by=self.user,
        )

    def test_generate_receipt_pdf_returns_pdf_bytes(self) -> None:
        from orders.services.receipt_pdf_service import (
            ReceiptContactSnapshot,
            generate_receipt_pdf,
        )

        signature = (
            "data:image/png;base64,"
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/"
            "x8AAwMCAO+/p9sAAAAASUVORK5CYII="
        )
        pdf_bytes = generate_receipt_pdf(
            order=self.order,
            contact=ReceiptContactSnapshot(
                name="Ana Lopez",
                email="ana@example.com",
                phone="4421234567",
                position="Compras",
            ),
            signature_data_url=signature,
        )

        self.assertTrue(pdf_bytes.startswith(b"%PDF"))
        self.assertGreater(len(pdf_bytes), 1000)

    def test_generate_receipt_pdf_rejects_invalid_signature_data(self) -> None:
        from orders.services.receipt_pdf_service import (
            ReceiptContactSnapshot,
            ReceiptPdfError,
            generate_receipt_pdf,
        )

        with self.assertRaisesMessage(ReceiptPdfError, "firma"):
            generate_receipt_pdf(
                order=self.order,
                contact=ReceiptContactSnapshot(
                    name="Ana Lopez",
                    email="ana@example.com",
                    phone="4421234567",
                    position="Compras",
                ),
                signature_data_url="not-a-data-url",
            )


class ReceiptDeliveryServiceTests(FastTenantTestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(username="delivery-user", password="testpass")
        self.customer = Client.objects.create(name="Delivery Client")
        self.order = Order.objects.create(
            client=self.customer,
            owner=self.user,
            status=OrderStatus.COMPLETED.value,
            total_amount=Decimal("80.00"),
        )

    @patch("orders.services.receipt_delivery_service.get_receipt_storage")
    @patch("orders.services.receipt_delivery_service.SendEmail")
    def test_delivery_sends_receipt_pdf_attachment_and_sets_sent_at(
        self,
        send_email_cls: MagicMock,
        storage_factory: MagicMock,
    ) -> None:
        from orders.models import OrderReceipt, ReceiptDeliveryMethod
        from orders.services.receipt_delivery_service import ReceiptDeliveryService

        storage_factory.return_value.download_pdf.return_value = b"%PDF-private"
        receipt = OrderReceipt.objects.create(
            order=self.order,
            method=ReceiptDeliveryMethod.EMAIL,
            pdf_url="receipts/orders/1/receipt.pdf",
            contact_name="Ana Lopez",
            contact_email="ana@example.com",
            created_by=self.user,
        )

        sent = ReceiptDeliveryService().send(receipt)

        self.assertIsNotNone(sent.sent_at)
        email_instance = send_email_cls.return_value
        email_instance.send_email.assert_called_once()
        attachment = send_email_cls.call_args.kwargs["attachments"][0]
        self.assertEqual(attachment.filename, f"recibo-pedido-{self.order.pk}.pdf")
        self.assertEqual(attachment.content, b"%PDF-private")

    @patch("orders.services.receipt_delivery_service.get_receipt_storage")
    @patch("orders.services.receipt_delivery_service.SendEmail")
    def test_delivery_failure_leaves_receipt_unsent(
        self,
        send_email_cls: MagicMock,
        storage_factory: MagicMock,
    ) -> None:
        from orders.models import OrderReceipt, ReceiptDeliveryMethod
        from orders.services.receipt_delivery_service import (
            ReceiptDeliveryError,
            ReceiptDeliveryService,
        )

        storage_factory.return_value.download_pdf.return_value = b"%PDF-private"
        send_email_cls.return_value.send_email.side_effect = RuntimeError("mailgun down")
        receipt = OrderReceipt.objects.create(
            order=self.order,
            method=ReceiptDeliveryMethod.EMAIL,
            pdf_url="receipts/orders/1/receipt.pdf",
            contact_name="Ana Lopez",
            contact_email="ana@example.com",
            created_by=self.user,
        )

        with self.assertRaises(ReceiptDeliveryError):
            ReceiptDeliveryService().send(receipt)

        receipt.refresh_from_db()
        self.assertIsNone(receipt.sent_at)


class OrderReceiptSignFormTests(FastTenantTestCase):
    def setUp(self) -> None:
        self.customer = Client.objects.create(name="Form Client")

    def test_form_preselects_single_contact(self) -> None:
        from clients.models import Contact
        from orders.forms import OrderReceiptSignForm

        contact = Contact.objects.create(
            client=self.customer,
            name="Ana Lopez",
            email="ana@example.com",
            phone="4421234567",
            position="Compras",
        )

        form = OrderReceiptSignForm(client=self.customer)

        self.assertEqual(form.fields["contact_id"].initial, contact.pk)
        self.assertEqual(form.fields["contact_name"].initial, "Ana Lopez")
        self.assertEqual(form.fields["contact_email"].initial, "ana@example.com")

    def test_form_exposes_dropdown_when_multiple_contacts_exist(self) -> None:
        from clients.models import Contact
        from orders.forms import OrderReceiptSignForm

        first = Contact.objects.create(
            client=self.customer,
            name="Ana",
            email="ana@example.com",
        )
        second = Contact.objects.create(
            client=self.customer,
            name="Luis",
            email="luis@example.com",
        )

        form = OrderReceiptSignForm(client=self.customer)

        choices = list(form.fields["contact_id"].choices)
        self.assertIn((first.pk, "Ana - ana@example.com"), choices)
        self.assertIn((second.pk, "Luis - luis@example.com"), choices)


class ReceiptServiceTests(FastTenantTestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username="receipt-service-user",
            password="testpass",
        )
        self.customer = Client.objects.create(name="Service Client")
        self.order = Order.objects.create(
            client=self.customer,
            owner=self.user,
            status=OrderStatus.COMPLETED.value,
            total_amount=Decimal("75.00"),
        )
        self.cleaned_data = {
            "method": "email",
            "contact_name": "Ana Lopez",
            "contact_email": "ana@example.com",
            "contact_phone": "4421234567",
            "contact_position": "Compras",
            "signature_data": (
                "data:image/png;base64,"
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/"
                "x8AAwMCAO+/p9sAAAAASUVORK5CYII="
            ),
        }

    @patch("orders.services.receipt_service.ReceiptDeliveryService")
    @patch("orders.services.receipt_service.get_receipt_storage")
    @patch("orders.services.receipt_service.generate_receipt_pdf")
    def test_create_signed_receipt_uploads_pdf_and_sends_email(
        self,
        pdf_mock: MagicMock,
        storage_factory: MagicMock,
        delivery_cls: MagicMock,
    ) -> None:
        from orders.models import OrderReceipt
        from orders.services.receipt_service import create_signed_receipt

        pdf_mock.return_value = b"%PDF-created"
        storage_factory.return_value.upload_pdf.return_value = "receipts/orders/1/receipt.pdf"

        result = create_signed_receipt(
            order=self.order,
            cleaned_data=self.cleaned_data,
            user=self.user,
        )

        receipt = OrderReceipt.objects.get(order=self.order)
        self.assertTrue(result.created)
        self.assertTrue(result.delivery_succeeded)
        self.assertEqual(receipt.contact_email, "ana@example.com")
        self.assertEqual(receipt.pdf_url, "receipts/orders/1/receipt.pdf")
        delivery_cls.return_value.send.assert_called_once_with(receipt)

    @patch("orders.services.receipt_service.ReceiptDeliveryService")
    @patch("orders.services.receipt_service.get_receipt_storage")
    @patch("orders.services.receipt_service.generate_receipt_pdf")
    def test_create_signed_receipt_keeps_unsent_receipt_when_delivery_fails(
        self,
        pdf_mock: MagicMock,
        storage_factory: MagicMock,
        delivery_cls: MagicMock,
    ) -> None:
        from orders.models import OrderReceipt
        from orders.services.receipt_delivery_service import ReceiptDeliveryError
        from orders.services.receipt_service import create_signed_receipt

        pdf_mock.return_value = b"%PDF-created"
        storage_factory.return_value.upload_pdf.return_value = "receipts/orders/1/receipt.pdf"
        delivery_cls.return_value.send.side_effect = ReceiptDeliveryError("mailgun down")

        result = create_signed_receipt(
            order=self.order,
            cleaned_data=self.cleaned_data,
            user=self.user,
        )

        receipt = OrderReceipt.objects.get(order=self.order)
        self.assertTrue(result.created)
        self.assertFalse(result.delivery_succeeded)
        self.assertEqual(result.delivery_error, "mailgun down")
        self.assertIsNone(receipt.sent_at)

    def test_create_signed_receipt_rejects_pending_order(self) -> None:
        from orders.services.receipt_service import (
            ReceiptCreationError,
            create_signed_receipt,
        )

        self.order.status = OrderStatus.PENDING.value
        self.order.save(update_fields=["status"])

        with self.assertRaisesMessage(ReceiptCreationError, "completados"):
            create_signed_receipt(
                order=self.order,
                cleaned_data=self.cleaned_data,
                user=self.user,
            )

    @patch("orders.services.receipt_service.generate_receipt_pdf")
    def test_create_signed_receipt_rejects_missing_email_before_pdf_generation(
        self,
        pdf_mock: MagicMock,
    ) -> None:
        from orders.services.receipt_service import (
            ReceiptCreationError,
            create_signed_receipt,
        )

        self.cleaned_data["contact_email"] = ""

        with self.assertRaisesMessage(ReceiptCreationError, "correo"):
            create_signed_receipt(
                order=self.order,
                cleaned_data=self.cleaned_data,
                user=self.user,
            )

        pdf_mock.assert_not_called()

    @patch("orders.services.receipt_service.ReceiptDeliveryService")
    def test_resend_receipt_reuses_existing_receipt(
        self,
        delivery_cls: MagicMock,
    ) -> None:
        from orders.models import OrderReceipt, ReceiptDeliveryMethod
        from orders.services.receipt_service import resend_receipt

        receipt = OrderReceipt.objects.create(
            order=self.order,
            method=ReceiptDeliveryMethod.EMAIL,
            pdf_url="receipts/orders/1/receipt.pdf",
            contact_name="Ana Lopez",
            contact_email="ana@example.com",
            created_by=self.user,
        )
        delivery_cls.return_value.send.return_value = receipt

        result = resend_receipt(receipt)

        self.assertFalse(result.created)
        self.assertTrue(result.delivery_succeeded)
        self.assertEqual(result.receipt.pdf_url, "receipts/orders/1/receipt.pdf")
        delivery_cls.return_value.send.assert_called_once_with(receipt)


class OrderReceiptViewTests(FastTenantTestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(username="receipt-view-user", password="testpass")
        self.client.force_login(self.user)
        self.customer = Client.objects.create(name="Receipt View Client")
        self.order = Order.objects.create(
            client=self.customer,
            owner=self.user,
            status=OrderStatus.COMPLETED.value,
            total_amount=Decimal("95.00"),
        )

    def test_sign_receipt_requires_login(self) -> None:
        self.client.logout()

        response = self.client.get(reverse("orders:sign_receipt", args=[self.order.pk]))

        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.url)

    def test_sign_receipt_rejects_pending_order(self) -> None:
        self.order.status = OrderStatus.PENDING.value
        self.order.save(update_fields=["status"])

        response = self.client.get(reverse("orders:sign_receipt", args=[self.order.pk]))

        self.assertEqual(response.status_code, 302)

    @patch("orders.views.create_signed_receipt")
    def test_sign_receipt_post_uses_service(self, create_receipt_mock: MagicMock) -> None:
        from orders.models import OrderReceipt, ReceiptDeliveryMethod
        from orders.services.receipt_service import ReceiptCreationResult

        receipt = OrderReceipt.objects.create(
            order=self.order,
            method=ReceiptDeliveryMethod.EMAIL,
            pdf_url="receipts/orders/1/receipt.pdf",
            contact_name="Ana Lopez",
            contact_email="ana@example.com",
            created_by=self.user,
        )
        create_receipt_mock.return_value = ReceiptCreationResult(
            receipt=receipt,
            created=True,
            delivery_succeeded=True,
            delivery_error="",
        )

        response = self.client.post(
            reverse("orders:sign_receipt", args=[self.order.pk]),
            data={
                "method": "email",
                "contact_name": "Ana Lopez",
                "contact_email": "ana@example.com",
                "contact_phone": "4421234567",
                "contact_position": "Compras",
                "signature_data": (
                    "data:image/png;base64,"
                    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/"
                    "x8AAwMCAO+/p9sAAAAASUVORK5CYII="
                ),
            },
        )

        self.assertEqual(response.status_code, 302)
        create_receipt_mock.assert_called_once()

    @patch("orders.views.resend_receipt")
    def test_resend_receipt_view_uses_existing_receipt(self, resend_mock: MagicMock) -> None:
        from orders.models import OrderReceipt, ReceiptDeliveryMethod
        from orders.services.receipt_service import ReceiptCreationResult

        receipt = OrderReceipt.objects.create(
            order=self.order,
            method=ReceiptDeliveryMethod.EMAIL,
            pdf_url="receipts/orders/1/receipt.pdf",
            contact_name="Ana Lopez",
            contact_email="ana@example.com",
            created_by=self.user,
        )
        resend_mock.return_value = ReceiptCreationResult(
            receipt=receipt,
            created=False,
            delivery_succeeded=True,
            delivery_error="",
        )

        response = self.client.post(reverse("orders:resend_receipt", args=[self.order.pk]))

        self.assertEqual(response.status_code, 302)
        resend_mock.assert_called_once_with(receipt)


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
    """Tests for dashboard bulk action business behavior."""

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

    def test_dashboard_bulk_create_invoice_allows_same_corporate_branches(self) -> None:
        branch_one = Client.objects.create(
            name='Bulk Branch One',
            type='branch',
            corporate=self.customer,
        )
        branch_two = Client.objects.create(
            name='Bulk Branch Two',
            type='branch',
            corporate=self.customer,
        )
        order_one = Order.objects.create(
            client=branch_one,
            owner=self.user,
            status=OrderStatus.COMPLETED.value,
            total_amount=Decimal('15.00'),
        )
        order_two = Order.objects.create(
            client=branch_two,
            owner=self.user,
            status=OrderStatus.COMPLETED.value,
            total_amount=Decimal('25.00'),
        )

        response = self.client.post(
            reverse('admin_orders'),
            data={
                'bulk_action': 'create_invoice',
                'selected_orders': [order_one.pk, order_two.pk],
            },
        )

        self.assertEqual(response.status_code, 302)
        invoice = Invoice.objects.get(client=self.customer)
        self.assertEqual(invoice.amount, Decimal('40.00'))
        self.assertSetEqual(
            set(invoice.invoice_links.values_list('order_id', flat=True)),
            {order_one.pk, order_two.pk},
        )

    def test_dashboard_bulk_create_invoice_rejects_different_fiscal_owners(self) -> None:
        branch = Client.objects.create(
            name='Bulk Branch',
            type='branch',
            corporate=self.customer,
        )
        other_branch = Client.objects.create(
            name='Other Bulk Branch',
            type='branch',
            corporate=self.other_customer,
        )
        order_one = Order.objects.create(
            client=branch,
            owner=self.user,
            status=OrderStatus.COMPLETED.value,
            total_amount=Decimal('15.00'),
        )
        order_two = Order.objects.create(
            client=other_branch,
            owner=self.user,
            status=OrderStatus.COMPLETED.value,
            total_amount=Decimal('25.00'),
        )

        response = self.client.post(
            reverse('admin_orders'),
            data={
                'bulk_action': 'create_invoice',
                'selected_orders': [order_one.pk, order_two.pk],
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Invoice.objects.count(), 0)

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


class OrdersAdminInvoiceActionTestCase(FastTenantTestCase):
    """Tests for the Django admin order invoice action."""

    def setUp(self) -> None:
        self.user = User.objects.create_superuser(
            username='order_admin_user',
            password='testpass',
        )
        self.factory = RequestFactory()
        self.order_admin = OrderAdmin(Order, admin.site)
        self.order_admin.message_user = MagicMock()
        self.customer = Client.objects.create(name='Admin Bulk Client', type='corporate')
        self._make_invoice_ready(self.customer)

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

    def _request(self):
        request = self.factory.post('/admin/orders/order/')
        request.user = self.user
        return request

    def test_admin_action_allows_same_corporate_branches(self) -> None:
        branch_one = Client.objects.create(
            name='Admin Branch One',
            type='branch',
            corporate=self.customer,
        )
        branch_two = Client.objects.create(
            name='Admin Branch Two',
            type='branch',
            corporate=self.customer,
        )
        order_one = Order.objects.create(
            client=branch_one,
            owner=self.user,
            status=OrderStatus.COMPLETED.value,
            total_amount=Decimal('15.00'),
        )
        order_two = Order.objects.create(
            client=branch_two,
            owner=self.user,
            status=OrderStatus.COMPLETED.value,
            total_amount=Decimal('25.00'),
        )

        response = self.order_admin.crear_factura(
            self._request(),
            Order.objects.filter(pk__in=[order_one.pk, order_two.pk]),
        )

        self.assertEqual(response.status_code, 302)
        invoice = Invoice.objects.get(client=self.customer)
        self.assertEqual(invoice.amount, Decimal('40.00'))
        self.assertSetEqual(
            set(invoice.invoice_links.values_list('order_id', flat=True)),
            {order_one.pk, order_two.pk},
        )


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
