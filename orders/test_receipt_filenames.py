from datetime import date, datetime, timezone as datetime_timezone
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, unquote, urlparse

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse

from clients.models import Client
from core.models import Transport
from orders.models import Order, OrderReceipt, OrderStatus
from orders.services.receipt_delivery_service import (
    EmailReceiptSender,
    ReceiptBundleDeliveryService,
    WhatsAppReceiptSender,
)
from orders.services.receipt_storage_service import (
    CloudflareR2ReceiptStorage,
    ReceiptStorageConfig,
)
from routes.models import Route, RouteClientOrder
from tenant_client.test_utils import FastTenantTestCase


@override_settings(TIME_ZONE="America/Mexico_City")
class ReceiptFilenameTests(FastTenantTestCase):
    def setUp(self) -> None:
        corporate = Client.objects.create(name="Corporativo fiscal", type="corporate")
        self.customer = Client.objects.create(
            name="Café / México Norte",
            corporate=corporate,
        )
        self.order = Order.objects.create(
            pk=701,
            client=self.customer,
            total_amount="25.00",
            status=OrderStatus.COMPLETED.value,
        )
        # UTC November 3 is still November 2 in Mexico City.
        self.order.order_date = datetime(2026, 11, 3, 4, tzinfo=datetime_timezone.utc)
        Order.objects.filter(pk=self.order.pk).update(order_date=self.order.order_date)
        self.receipt = OrderReceipt.objects.create(
            order=self.order,
            contact_name="Otro contacto",
            contact_email="contacto@example.com",
            contact_phone="4421234567",
            pdf_url="receipts/orders/701/receipt.pdf",
        )
        transport = Transport.objects.create(
            license_plate="PDF-701",
            model="Camioneta",
            capacity_liters=1000,
        )
        self.route = Route.objects.create(
            name="Ruta recibos",
            transportation=transport,
            weekday="thursday",
        )
        self.delivery = RouteClientOrder.objects.create(
            route=self.route,
            client=self.customer,
            order=self.order,
            sequence=1,
            visit_date=date(2026, 11, 4),
            is_completed=True,
            completed_at=datetime(2026, 11, 6, 3, tzinfo=datetime_timezone.utc),
        )
        self.storage = CloudflareR2ReceiptStorage(
            ReceiptStorageConfig(
                endpoint_url="https://receipt-tests.example.com",
                bucket_name="receipts",
                access_key_id="test-key",
                secret_access_key="test-secret",
                region="auto",
                object_prefix="receipts",
                signed_url_expires_seconds=86400,
            )
        )

    def _email_attachment(self) -> tuple[str, bytes, str]:
        with (
            patch(
                "orders.services.receipt_delivery_service.get_receipt_storage",
                return_value=self.storage,
            ),
            patch.object(self.storage, "download_pdf", return_value=b"%PDF-test"),
            patch(
                "notification.channels.email.requests.post",
                return_value=Mock(status_code=200, text="Queued"),
            ) as post,
        ):
            EmailReceiptSender().send(self.receipt)
        return post.call_args.kwargs["files"][0][1]

    def test_email_names_pdf_for_order_client_actual_local_delivery_and_id(self) -> None:
        self.assertEqual(
            self._email_attachment(),
            ("cafe-mexico-norte-2026-11-05-701.pdf", b"%PDF-test", "application/pdf"),
        )

    def test_missing_completion_uses_scheduled_delivery_date(self) -> None:
        self.delivery.completed_at = None
        self.delivery.save(update_fields=["completed_at"])

        self.assertEqual(
            self._email_attachment()[0],
            "cafe-mexico-norte-2026-11-04-701.pdf",
        )

    def test_order_without_route_uses_its_local_order_date(self) -> None:
        self.delivery.delete()

        self.assertEqual(
            self._email_attachment()[0],
            "cafe-mexico-norte-2026-11-02-701.pdf",
        )

    def test_filename_safely_normalizes_customer_name(self) -> None:
        self.customer.name = '../\r\nCafé "Centro" \\ Sur_2'

        self.assertEqual(
            self._email_attachment()[0],
            "cafe-centro-sur-2-2026-11-05-701.pdf",
        )

    def test_name_without_slug_characters_has_customer_fallback(self) -> None:
        self.customer.name = "!!!"

        self.assertEqual(self._email_attachment()[0], "cliente-2026-11-05-701.pdf")

    def test_bundle_email_uses_each_orders_own_filename(self) -> None:
        second_customer = Client.objects.create(name="Sucursal Sur")
        second = Order.objects.create(
            pk=702,
            client=second_customer,
            total_amount="10.00",
            status=OrderStatus.COMPLETED.value,
        )
        second.order_date = datetime(2026, 10, 9, 12, tzinfo=datetime_timezone.utc)
        Order.objects.filter(pk=second.pk).update(order_date=second.order_date)
        OrderReceipt.objects.create(order=second, pdf_url="legacy/702.pdf")
        with (
            patch(
                "orders.services.receipt_delivery_service.get_receipt_storage",
                return_value=self.storage,
            ),
            patch.object(self.storage, "download_pdf", return_value=b"%PDF-test"),
            patch(
                "notification.channels.email.requests.post",
                return_value=Mock(status_code=200, text="Queued"),
            ) as post,
        ):
            ReceiptBundleDeliveryService().send(
                orders=[self.order, second],
                recipient_name="Administración",
                recipient_email="contacto@example.com",
            )

        self.assertEqual(
            [attachment[1][0] for attachment in post.call_args.kwargs["files"]],
            ["cafe-mexico-norte-2026-11-05-701.pdf", "sucursal-sur-2026-10-09-702.pdf"],
        )

    def test_whatsapp_link_overrides_download_name_for_existing_storage_key(self) -> None:
        with patch(
            "orders.services.receipt_delivery_service.get_receipt_storage",
            return_value=self.storage,
        ):
            outcome = WhatsAppReceiptSender().send(self.receipt)

        message = parse_qs(urlparse(outcome.delivery_url).query)["text"][0]
        signed_url = next(
            line for line in message.splitlines() if line.startswith("https:")
        )
        self._assert_signed_filename(signed_url)

    def test_pdf_download_view_overrides_name_for_existing_storage_key(self) -> None:
        user = get_user_model().objects.create_user(username="receipt-user")
        self.client.force_login(user)
        with patch("orders.views.get_receipt_storage", return_value=self.storage):
            response = self.client.get(
                reverse("orders:receipt_pdf", kwargs={"order_id": self.order.pk})
            )

        self.assertEqual(response.status_code, 302)
        self._assert_signed_filename(response["Location"])

    def _assert_signed_filename(self, signed_url: str) -> None:
        parsed = urlparse(signed_url)
        self.assertEqual(unquote(parsed.path), "/receipts/receipts/orders/701/receipt.pdf")
        self.assertEqual(
            parse_qs(parsed.query).get("response-content-disposition"),
            ['inline; filename="cafe-mexico-norte-2026-11-05-701.pdf"'],
        )
