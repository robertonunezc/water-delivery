# Order Receipt Signature Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one private signed PDF receipt per completed order, with authenticated mobile signing, R2 storage, and email attachment delivery.

**Architecture:** Add an `OrderReceipt` one-to-one model, then keep receipt orchestration in focused order services: PDF generation, private R2 storage, and delivery through a sender registry/factory. The existing payment flow remains responsible for completing orders; receipt UI only changes the post-success redirect when the checkbox is checked.

**Tech Stack:** Django 5.2, Django templates, vanilla JavaScript canvas, boto3 for Cloudflare R2, Mailgun HTTP email, reportlab for PDF generation, Django test runner.

**Spec:** `docs/superpowers/specs/2026-09-14-order-receipt-signature-design.md`

## Global Constraints

- Checkbox text must be exactly `Firmar y enviar recibo`.
- Payment/order completion must happen before redirecting to the receipt signing form.
- Completed orders have a reusable sign, retry, or resend receipt action.
- Store exactly one signed receipt per order and reuse that signed PDF forever.
- Receipt PDFs are private Cloudflare R2 objects; no public or permanent PDF links.
- Email delivery sends the signed PDF as an attachment.
- Authenticated users only; no extra role-specific permission checks.
- Contact fields are editable and saved as a receipt snapshot.
- Signature image is embedded into the PDF and is not stored separately.
- If PDF upload succeeds but email fails, keep the receipt saved with `sent_at = null`.
- Use a sender registry/factory for delivery; implement email only in this iteration.
- Add backend/model/service/view tests. No UI tests.
- Use existing soft-delete managers; do not assume default managers return deleted rows.
- Type hints are required for all new function signatures.

---

## File Structure

- Modify `requirements.txt`: add `reportlab` for PDF generation.
- Modify `water_delivery/settings.py`: add R2 receipt settings read from env vars.
- Modify `notification/channels/email.py`: support email attachments through the existing Mailgun HTTP sender.
- Modify `orders/models.py`: add `OrderReceipt` and delivery method choices.
- Create `orders/migrations/0020_orderreceipt.py`: migration for `OrderReceipt`.
- Modify `orders/admin.py`: register or inline-display receipt metadata for admin visibility.
- Create `orders/services/receipt_storage_service.py`: upload/download receipt PDFs from private R2.
- Create `orders/services/receipt_pdf_service.py`: render signed receipt PDF bytes.
- Create `orders/services/receipt_delivery_service.py`: sender registry/factory and email sender.
- Create `orders/services/receipt_service.py`: orchestration for create, retry, and resend.
- Modify `orders/forms.py`: add authenticated signing/contact snapshot form.
- Modify `orders/views.py`: add sign and resend views, add receipt URLs to order page context, select receipt in list querysets.
- Modify `orders/urls.py`: route signing and resend endpoints.
- Create `orders/templates/orders/receipt_sign.html`: mobile-friendly signing form.
- Create `orders/static/orders/js/receipt_sign.js`: canvas signature and contact dropdown behavior.
- Modify `orders/templates/create_order.html`: add checkbox and signing URL data below finish button.
- Modify `orders/static/orders/js/create_order.js`: redirect to signing page after successful completion when checked.
- Modify `orders/templates/orders/list_order.html`: add completed-order receipt action.
- Modify `orders/templates/admin/orders/pedidos_list.html`: add completed-order receipt action.
- Modify `clients/templates/client_detail.html`: add completed-order receipt action in the client order dropdown.
- Modify `orders/tests.py`: add model, form, view, service, delivery, and create-order redirect tests.

---

### Task 1: Receipt Model, Migration, And Admin Visibility

**Files:**
- Modify: `orders/models.py`
- Create: `orders/migrations/0020_orderreceipt.py`
- Modify: `orders/admin.py`
- Test: `orders/tests.py`

**Interfaces:**
- Consumes: `core.models.TimeStampedModel`, `orders.models.Order`
- Produces: `OrderReceipt`
- Produces: `ReceiptDeliveryMethod.EMAIL = "email"`
- Produces: `Order.receipt` one-to-one relation

- [ ] **Step 1: Write failing model tests**

Add this test class near the existing order model tests in `orders/tests.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test orders.tests.OrderReceiptModelTests -q`

Expected: FAIL with an import error for `OrderReceipt`.

- [ ] **Step 3: Add model code**

Append to `orders/models.py` after `OrderSplit`:

```python
RECEIPT_DELIVERY_METHOD_CHOICES = (
    ("email", "Email"),
    ("sms", "SMS"),
    ("whatsapp", "WhatsApp"),
)


class ReceiptDeliveryMethod:
    EMAIL = "email"
    SMS = "sms"
    WHATSAPP = "whatsapp"


class OrderReceipt(TimeStampedModel):
    order = models.OneToOneField(
        "Order",
        on_delete=models.PROTECT,
        related_name="receipt",
        verbose_name="Pedido",
    )
    method = models.CharField(
        max_length=20,
        choices=RECEIPT_DELIVERY_METHOD_CHOICES,
        default=ReceiptDeliveryMethod.EMAIL,
        verbose_name="Metodo de envio",
    )
    sent_at = models.DateTimeField(null=True, blank=True, verbose_name="Enviado en")
    pdf_url = models.CharField(max_length=500, verbose_name="PDF privado")
    contact_name = models.CharField(max_length=100, verbose_name="Nombre de contacto")
    contact_email = models.EmailField(verbose_name="Correo de contacto")
    contact_phone = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        verbose_name="Telefono de contacto",
    )
    contact_position = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name="Puesto de contacto",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_order_receipts",
        verbose_name="Creado por",
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Recibo de pedido"
        verbose_name_plural = "Recibos de pedidos"
        indexes = [
            models.Index(fields=["method"], name="orders_receipt_method_idx"),
            models.Index(fields=["sent_at"], name="orders_receipt_sent_idx"),
        ]

    def __str__(self) -> str:
        return f"Recibo pedido #{self.order_id} - {self.method}"
```

- [ ] **Step 4: Create migration**

Run: `python manage.py makemigrations orders`

Expected: creates `orders/migrations/0020_orderreceipt.py` with the `OrderReceipt` model.

- [ ] **Step 5: Add admin registration**

In `orders/admin.py`, import `OrderReceipt` and register it:

```python
from .models import Order, OrderProduct, OrderReceipt, OrderSplit
```

```python
@admin.register(OrderReceipt)
class OrderReceiptAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "order",
        "method",
        "contact_email",
        "sent_at",
        "created_at",
    )
    search_fields = (
        "order__id",
        "order__client__name",
        "contact_name",
        "contact_email",
    )
    list_filter = ("method", "sent_at", "created_at")
    readonly_fields = ("created_at", "updated_at", "deleted_at")
```

- [ ] **Step 6: Run model tests**

Run: `python manage.py test orders.tests.OrderReceiptModelTests -q`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add orders/models.py orders/admin.py orders/migrations/0020_orderreceipt.py orders/tests.py
git commit -m "feat: add order receipt model"
```

---

### Task 2: Private R2 Receipt Storage Service

**Files:**
- Modify: `water_delivery/settings.py`
- Create: `orders/services/receipt_storage_service.py`
- Test: `orders/tests.py`

**Interfaces:**
- Consumes: Django settings `RECEIPT_R2_*`
- Produces: `ReceiptStorageError`
- Produces: `CloudflareR2ReceiptStorage.upload_pdf(order_id: int, pdf_bytes: bytes) -> str`
- Produces: `CloudflareR2ReceiptStorage.download_pdf(pdf_url: str) -> bytes`
- Produces: `CloudflareR2ReceiptStorage.generate_signed_url(pdf_url: str) -> str`
- Produces: `get_receipt_storage() -> CloudflareR2ReceiptStorage`

- [ ] **Step 1: Write failing storage tests**

Add this class to `orders/tests.py`:

```python
from django.test import RequestFactory, override_settings
```

Then add:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test orders.tests.ReceiptStorageServiceTests -q`

Expected: FAIL because `orders.services.receipt_storage_service` does not exist.

- [ ] **Step 3: Add settings**

Add to `water_delivery/settings.py` near media/static settings:

```python
RECEIPT_R2_ENDPOINT_URL = os.getenv("RECEIPT_R2_ENDPOINT_URL", "")
RECEIPT_R2_BUCKET_NAME = os.getenv("RECEIPT_R2_BUCKET_NAME", "")
RECEIPT_R2_ACCESS_KEY_ID = os.getenv("RECEIPT_R2_ACCESS_KEY_ID", "")
RECEIPT_R2_SECRET_ACCESS_KEY = os.getenv("RECEIPT_R2_SECRET_ACCESS_KEY", "")
RECEIPT_R2_OBJECT_PREFIX = os.getenv("RECEIPT_R2_OBJECT_PREFIX", "receipts")
RECEIPT_R2_SIGNED_URL_EXPIRES_SECONDS = int(
    os.getenv("RECEIPT_R2_SIGNED_URL_EXPIRES_SECONDS", "900")
)
```

- [ ] **Step 4: Implement storage service**

Create `orders/services/receipt_storage_service.py`:

```python
from __future__ import annotations

from dataclasses import dataclass

import boto3
from botocore.config import Config
from django.conf import settings


class ReceiptStorageError(RuntimeError):
    """Raised when receipt PDF storage cannot complete."""


@dataclass(frozen=True)
class ReceiptStorageConfig:
    endpoint_url: str
    bucket_name: str
    access_key_id: str
    secret_access_key: str
    object_prefix: str
    signed_url_expires_seconds: int


class CloudflareR2ReceiptStorage:
    def __init__(self, config: ReceiptStorageConfig):
        self.config = config
        self.client = boto3.client(
            "s3",
            endpoint_url=config.endpoint_url,
            aws_access_key_id=config.access_key_id,
            aws_secret_access_key=config.secret_access_key,
            config=Config(signature_version="s3v4"),
        )

    @classmethod
    def from_settings(cls) -> "CloudflareR2ReceiptStorage":
        config = ReceiptStorageConfig(
            endpoint_url=settings.RECEIPT_R2_ENDPOINT_URL,
            bucket_name=settings.RECEIPT_R2_BUCKET_NAME,
            access_key_id=settings.RECEIPT_R2_ACCESS_KEY_ID,
            secret_access_key=settings.RECEIPT_R2_SECRET_ACCESS_KEY,
            object_prefix=settings.RECEIPT_R2_OBJECT_PREFIX.strip("/"),
            signed_url_expires_seconds=settings.RECEIPT_R2_SIGNED_URL_EXPIRES_SECONDS,
        )
        missing = [
            label
            for label, value in (
                ("RECEIPT_R2_ENDPOINT_URL", config.endpoint_url),
                ("RECEIPT_R2_BUCKET_NAME", config.bucket_name),
                ("RECEIPT_R2_ACCESS_KEY_ID", config.access_key_id),
                ("RECEIPT_R2_SECRET_ACCESS_KEY", config.secret_access_key),
            )
            if not value
        ]
        if missing:
            raise ReceiptStorageError(
                f"Cloudflare R2 receipt storage is not configured: {', '.join(missing)}"
            )
        return cls(config)

    def upload_pdf(self, order_id: int, pdf_bytes: bytes) -> str:
        key = self._object_key(order_id)
        self.client.put_object(
            Bucket=self.config.bucket_name,
            Key=key,
            Body=pdf_bytes,
            ContentType="application/pdf",
        )
        return key

    def download_pdf(self, pdf_url: str) -> bytes:
        response = self.client.get_object(
            Bucket=self.config.bucket_name,
            Key=pdf_url,
        )
        return response["Body"].read()

    def generate_signed_url(self, pdf_url: str) -> str:
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.config.bucket_name, "Key": pdf_url},
            ExpiresIn=self.config.signed_url_expires_seconds,
        )

    def _object_key(self, order_id: int) -> str:
        return f"{self.config.object_prefix}/orders/{order_id}/receipt.pdf"


def get_receipt_storage() -> CloudflareR2ReceiptStorage:
    return CloudflareR2ReceiptStorage.from_settings()
```

- [ ] **Step 5: Run storage tests**

Run: `python manage.py test orders.tests.ReceiptStorageServiceTests -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add water_delivery/settings.py orders/services/receipt_storage_service.py orders/tests.py
git commit -m "feat: add private receipt R2 storage"
```

---

### Task 3: Receipt PDF Generator

**Files:**
- Modify: `requirements.txt`
- Create: `orders/services/receipt_pdf_service.py`
- Test: `orders/tests.py`

**Interfaces:**
- Consumes: `Order`, prefetched `items__product`, prefetched `payments`
- Produces: `ReceiptContactSnapshot`
- Produces: `ReceiptPdfError`
- Produces: `generate_receipt_pdf(order: Order, contact: ReceiptContactSnapshot, signature_data_url: str) -> bytes`

- [ ] **Step 1: Write failing PDF tests**

Add this class to `orders/tests.py`:

```python
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
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test orders.tests.ReceiptPdfServiceTests -q`

Expected: FAIL because `orders.services.receipt_pdf_service` does not exist.

- [ ] **Step 3: Add PDF dependency**

Add to `requirements.txt`:

```text
reportlab==4.2.5
```

If the local environment lacks reportlab, run `pip install -r requirements.txt` before running this task's passing test.

- [ ] **Step 4: Implement PDF service**

Create `orders/services/receipt_pdf_service.py`:

```python
from __future__ import annotations

import base64
from dataclasses import dataclass
from decimal import Decimal
from io import BytesIO

from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from orders.models import Order


class ReceiptPdfError(ValueError):
    """Raised when a receipt PDF cannot be generated."""


@dataclass(frozen=True)
class ReceiptContactSnapshot:
    name: str
    email: str
    phone: str = ""
    position: str = ""


def generate_receipt_pdf(
    order: Order,
    contact: ReceiptContactSnapshot,
    signature_data_url: str,
) -> bytes:
    signature_bytes = _decode_signature(signature_data_url)
    output = BytesIO()
    document = SimpleDocTemplate(
        output,
        pagesize=letter,
        rightMargin=0.5 * inch,
        leftMargin=0.5 * inch,
        topMargin=0.5 * inch,
        bottomMargin=0.5 * inch,
    )
    styles = getSampleStyleSheet()
    elements = [
        Paragraph("PuriGest - Recibo de pedido", styles["Title"]),
        Paragraph(f"Pedido #{order.pk}", styles["Heading2"]),
        Paragraph(f"Cliente: {order.client.name}", styles["Normal"]),
        Paragraph(f"Fecha del pedido: {timezone.localtime(order.order_date):%d/%m/%Y %H:%M}", styles["Normal"]),
        Paragraph(f"Fecha del recibo: {timezone.localtime(timezone.now()):%d/%m/%Y %H:%M}", styles["Normal"]),
        Spacer(1, 0.2 * inch),
        Paragraph("Productos", styles["Heading3"]),
        _products_table(order),
        Spacer(1, 0.2 * inch),
        Paragraph("Pagos", styles["Heading3"]),
        _payments_table(order),
        Spacer(1, 0.2 * inch),
        _totals_table(order),
        Spacer(1, 0.2 * inch),
        Paragraph("Contacto", styles["Heading3"]),
        Paragraph(f"Nombre: {contact.name}", styles["Normal"]),
        Paragraph(f"Correo: {contact.email}", styles["Normal"]),
        Paragraph(f"Telefono: {contact.phone or 'Sin telefono'}", styles["Normal"]),
        Paragraph(f"Puesto: {contact.position or 'Sin puesto'}", styles["Normal"]),
        Spacer(1, 0.2 * inch),
        Paragraph("Firma", styles["Heading3"]),
        Image(BytesIO(signature_bytes), width=3.2 * inch, height=1.1 * inch),
    ]
    document.build(elements)
    return output.getvalue()


def _decode_signature(signature_data_url: str) -> bytes:
    prefix = "data:image/png;base64,"
    if not signature_data_url.startswith(prefix):
        raise ReceiptPdfError("La firma debe enviarse como imagen PNG.")
    try:
        return base64.b64decode(signature_data_url[len(prefix):], validate=True)
    except (ValueError, TypeError) as exc:
        raise ReceiptPdfError("La firma no es valida.") from exc


def _products_table(order: Order) -> Table:
    rows = [["Producto", "Cantidad", "Precio", "Total"]]
    for item in order.items.select_related("product").all():
        rows.append([
            item.product.get_full_name(),
            str(item.quantity),
            _money(item.unit_price),
            _money(item.get_total_price()),
        ])
    table = Table(rows, hAlign="LEFT")
    table.setStyle(_table_style())
    return table


def _payments_table(order: Order) -> Table:
    rows = [["Metodo", "Monto", "Fecha"]]
    payments = order.payments.not_reversed().all()
    for payment in payments:
        rows.append([
            payment.get_method_display(),
            _money(payment.amount),
            timezone.localtime(payment.date).strftime("%d/%m/%Y %H:%M"),
        ])
    if len(rows) == 1:
        rows.append(["Sin pagos", "$0.00", ""])
    table = Table(rows, hAlign="LEFT")
    table.setStyle(_table_style())
    return table


def _totals_table(order: Order) -> Table:
    rows = [
        ["Subtotal", _money(order.subtotal_amount)],
        ["Descuento", _money(order.discount)],
        ["Total", _money(order.total_amount)],
    ]
    if order.cantidad_cobrada is not None:
        rows.append(["Cantidad cobrada", _money(order.cantidad_cobrada)])
    table = Table(rows, hAlign="LEFT")
    table.setStyle(_table_style())
    return table


def _table_style() -> TableStyle:
    return TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("PADDING", (0, 0), (-1, -1), 6),
    ])


def _money(value: Decimal | int | float) -> str:
    return f"${Decimal(str(value or 0)):.2f}"
```

- [ ] **Step 5: Run PDF tests**

Run: `python manage.py test orders.tests.ReceiptPdfServiceTests -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add requirements.txt orders/services/receipt_pdf_service.py orders/tests.py
git commit -m "feat: generate signed order receipt PDFs"
```

---

### Task 4: Email Attachments And Receipt Delivery Factory

**Files:**
- Modify: `notification/channels/email.py`
- Create: `orders/services/receipt_delivery_service.py`
- Test: `orders/tests.py`

**Interfaces:**
- Consumes: `OrderReceipt`, `get_receipt_storage()`
- Produces: `EmailAttachment`
- Produces: `ReceiptDeliveryError`
- Produces: `ReceiptSenderFactory.get_sender(method: str) -> ReceiptSender`
- Produces: `ReceiptDeliveryService.send(receipt: OrderReceipt) -> OrderReceipt`

- [ ] **Step 1: Write failing email attachment tests**

Add to `orders/tests.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test orders.tests.ReceiptDeliveryServiceTests -q`

Expected: FAIL because `orders.services.receipt_delivery_service` does not exist.

- [ ] **Step 3: Extend Mailgun email sender with attachments**

Modify `notification/channels/email.py`:

```python
from dataclasses import dataclass
from typing import Iterable
```

```python
@dataclass(frozen=True)
class EmailAttachment:
    filename: str
    content: bytes
    content_type: str = "application/octet-stream"
```

Update `SendEmail.__init__`:

```python
def __init__(
    self,
    to: str,
    from_: str,
    subject: str,
    body: str,
    attachments: Iterable[EmailAttachment] | None = None,
):
    self.to = to
    self.from_ = from_
    self.subject = subject
    self.body = body
    self.attachments = list(attachments or [])
```

Update the `requests.post` call:

```python
files = [
    ("attachment", (attachment.filename, attachment.content, attachment.content_type))
    for attachment in self.attachments
]
response = requests.post(
    f"https://api.mailgun.net/v3/{from_domain}/messages",
    auth=("api", email_api_key),
    data={
        "from": self.from_,
        "to": self.to,
        "subject": self.subject,
        "text": self.body,
    },
    files=files or None,
)
```

- [ ] **Step 4: Implement delivery factory**

Create `orders/services/receipt_delivery_service.py`:

```python
from __future__ import annotations

from typing import Protocol

from django.conf import settings
from django.utils import timezone

from notification.channels.email import EmailAttachment, SendEmail
from orders.models import OrderReceipt, ReceiptDeliveryMethod
from orders.services.receipt_storage_service import get_receipt_storage


class ReceiptDeliveryError(RuntimeError):
    """Raised when a receipt cannot be delivered."""


class ReceiptSender(Protocol):
    def send(self, receipt: OrderReceipt) -> None:
        ...


class EmailReceiptSender:
    def send(self, receipt: OrderReceipt) -> None:
        pdf_bytes = get_receipt_storage().download_pdf(receipt.pdf_url)
        attachment = EmailAttachment(
            filename=f"recibo-pedido-{receipt.order_id}.pdf",
            content=pdf_bytes,
            content_type="application/pdf",
        )
        sender = SendEmail(
            to=receipt.contact_email,
            from_=getattr(settings, "RECEIPT_EMAIL_FROM", "WaterDelivery<soporte@puntoreica.com>"),
            subject=f"Recibo firmado pedido #{receipt.order_id}",
            body=(
                f"Adjuntamos el recibo firmado del pedido #{receipt.order_id}.\n\n"
                "Gracias."
            ),
            attachments=[attachment],
        )
        sender.send_email()


class ReceiptSenderFactory:
    def __init__(self) -> None:
        self._senders: dict[str, ReceiptSender] = {
            ReceiptDeliveryMethod.EMAIL: EmailReceiptSender(),
        }

    def get_sender(self, method: str) -> ReceiptSender:
        sender = self._senders.get(method)
        if sender is None:
            raise ReceiptDeliveryError(f"Metodo de envio no soportado: {method}")
        return sender


class ReceiptDeliveryService:
    def __init__(self, factory: ReceiptSenderFactory | None = None) -> None:
        self.factory = factory or ReceiptSenderFactory()

    def send(self, receipt: OrderReceipt) -> OrderReceipt:
        try:
            self.factory.get_sender(receipt.method).send(receipt)
        except Exception as exc:
            raise ReceiptDeliveryError(str(exc)) from exc

        receipt.sent_at = timezone.now()
        receipt.save(update_fields=["sent_at", "updated_at"])
        return receipt
```

- [ ] **Step 5: Run delivery tests**

Run: `python manage.py test orders.tests.ReceiptDeliveryServiceTests -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add notification/channels/email.py orders/services/receipt_delivery_service.py orders/tests.py
git commit -m "feat: add receipt email delivery service"
```

---

### Task 5: Receipt Signing Form And Orchestration Service

**Files:**
- Modify: `orders/forms.py`
- Create: `orders/services/receipt_service.py`
- Test: `orders/tests.py`

**Interfaces:**
- Consumes: `OrderReceipt`, `ReceiptContactSnapshot`, `generate_receipt_pdf`, `get_receipt_storage`, `ReceiptDeliveryService`
- Produces: `OrderReceiptSignForm(client: Client, data: QueryDict | None = None)`
- Produces: `create_signed_receipt(order: Order, cleaned_data: dict[str, object], user: User) -> ReceiptCreationResult`
- Produces: `resend_receipt(receipt: OrderReceipt) -> ReceiptCreationResult`

- [ ] **Step 1: Write failing form tests**

Add to `orders/tests.py`:

```python
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

        first = Contact.objects.create(client=self.customer, name="Ana", email="ana@example.com")
        second = Contact.objects.create(client=self.customer, name="Luis", email="luis@example.com")

        form = OrderReceiptSignForm(client=self.customer)

        choices = list(form.fields["contact_id"].choices)
        self.assertIn((first.pk, "Ana - ana@example.com"), choices)
        self.assertIn((second.pk, "Luis - luis@example.com"), choices)
```

- [ ] **Step 2: Write failing service tests**

Add to `orders/tests.py`:

```python
class ReceiptServiceTests(FastTenantTestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(username="receipt-service-user", password="testpass")
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
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
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
        from orders.services.receipt_service import ReceiptCreationError, create_signed_receipt

        self.order.status = OrderStatus.PENDING.value
        self.order.save(update_fields=["status"])

        with self.assertRaisesMessage(ReceiptCreationError, "completados"):
            create_signed_receipt(
                order=self.order,
                cleaned_data=self.cleaned_data,
                user=self.user,
            )
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python manage.py test orders.tests.OrderReceiptSignFormTests orders.tests.ReceiptServiceTests -q`

Expected: FAIL because form and receipt service are missing.

- [ ] **Step 4: Add signing form**

Add to `orders/forms.py`:

```python
from clients.models import Client, Contact
from orders.models import ReceiptDeliveryMethod
```

```python
class OrderReceiptSignForm(forms.Form):
    contact_id = forms.ChoiceField(required=False, label="Contacto")
    method = forms.ChoiceField(
        choices=((ReceiptDeliveryMethod.EMAIL, "Email"),),
        initial=ReceiptDeliveryMethod.EMAIL,
        widget=forms.HiddenInput(),
    )
    contact_name = forms.CharField(max_length=100, label="Nombre")
    contact_email = forms.EmailField(label="Correo electronico")
    contact_phone = forms.CharField(max_length=20, required=False, label="Telefono")
    contact_position = forms.CharField(max_length=100, required=False, label="Puesto")
    signature_data = forms.CharField(widget=forms.HiddenInput())

    def __init__(self, *args, client: Client, **kwargs):
        self.client = client
        super().__init__(*args, **kwargs)
        contacts = list(client.contacts.all().order_by("name", "id"))
        self.fields["contact_id"].choices = [
            (contact.pk, self._contact_label(contact))
            for contact in contacts
        ]
        if len(contacts) == 1 and not self.is_bound:
            self._apply_contact_initial(contacts[0])

    def clean_contact_id(self) -> str:
        value = self.cleaned_data.get("contact_id") or ""
        if not value:
            return ""
        if not self.client.contacts.filter(pk=value).exists():
            raise forms.ValidationError("Contacto invalido para este cliente.")
        return value

    def clean_signature_data(self) -> str:
        value = self.cleaned_data.get("signature_data", "")
        if not value.startswith("data:image/png;base64,"):
            raise forms.ValidationError("Capture la firma antes de enviar el recibo.")
        return value

    def _apply_contact_initial(self, contact: Contact) -> None:
        self.fields["contact_id"].initial = contact.pk
        self.fields["contact_name"].initial = contact.name
        self.fields["contact_email"].initial = contact.email or ""
        self.fields["contact_phone"].initial = contact.phone or ""
        self.fields["contact_position"].initial = contact.position or ""

    def _contact_label(self, contact: Contact) -> str:
        email = contact.email or "sin correo"
        return f"{contact.name} - {email}"
```

- [ ] **Step 5: Add orchestration service**

Create `orders/services/receipt_service.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.contrib.auth import get_user_model
from django.db import IntegrityError

from orders.models import Order, OrderReceipt, OrderStatus
from orders.services.receipt_delivery_service import ReceiptDeliveryError, ReceiptDeliveryService
from orders.services.receipt_pdf_service import ReceiptContactSnapshot, generate_receipt_pdf
from orders.services.receipt_storage_service import get_receipt_storage

User = get_user_model()


class ReceiptCreationError(ValueError):
    """Raised when a receipt cannot be created for an order."""


@dataclass(frozen=True)
class ReceiptCreationResult:
    receipt: OrderReceipt
    created: bool
    delivery_succeeded: bool
    delivery_error: str


def create_signed_receipt(
    order: Order,
    cleaned_data: dict[str, Any],
    user: User,
) -> ReceiptCreationResult:
    if order.status != OrderStatus.COMPLETED.value:
        raise ReceiptCreationError("Solo se pueden firmar recibos de pedidos completados.")

    existing = getattr(order, "receipt", None)
    if existing is not None:
        return ReceiptCreationResult(
            receipt=existing,
            created=False,
            delivery_succeeded=existing.sent_at is not None,
            delivery_error="",
        )

    contact = ReceiptContactSnapshot(
        name=str(cleaned_data["contact_name"]),
        email=str(cleaned_data["contact_email"]),
        phone=str(cleaned_data.get("contact_phone") or ""),
        position=str(cleaned_data.get("contact_position") or ""),
    )
    pdf_bytes = generate_receipt_pdf(
        order=order,
        contact=contact,
        signature_data_url=str(cleaned_data["signature_data"]),
    )
    pdf_url = get_receipt_storage().upload_pdf(order_id=order.pk, pdf_bytes=pdf_bytes)

    try:
        receipt = OrderReceipt.objects.create(
            order=order,
            method=str(cleaned_data.get("method") or "email"),
            pdf_url=pdf_url,
            contact_name=contact.name,
            contact_email=contact.email,
            contact_phone=contact.phone or None,
            contact_position=contact.position or None,
            created_by=user,
        )
    except IntegrityError:
        receipt = OrderReceipt.objects.get(order=order)
        return ReceiptCreationResult(
            receipt=receipt,
            created=False,
            delivery_succeeded=receipt.sent_at is not None,
            delivery_error="",
        )

    return _send_receipt(receipt=receipt, created=True)


def resend_receipt(receipt: OrderReceipt) -> ReceiptCreationResult:
    return _send_receipt(receipt=receipt, created=False)


def _send_receipt(receipt: OrderReceipt, created: bool) -> ReceiptCreationResult:
    try:
        sent = ReceiptDeliveryService().send(receipt)
    except ReceiptDeliveryError as exc:
        return ReceiptCreationResult(
            receipt=receipt,
            created=created,
            delivery_succeeded=False,
            delivery_error=str(exc),
        )
    return ReceiptCreationResult(
        receipt=sent,
        created=created,
        delivery_succeeded=True,
        delivery_error="",
    )
```

- [ ] **Step 6: Run form and service tests**

Run: `python manage.py test orders.tests.OrderReceiptSignFormTests orders.tests.ReceiptServiceTests -q`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add orders/forms.py orders/services/receipt_service.py orders/tests.py
git commit -m "feat: add receipt signing orchestration"
```

---

### Task 6: Receipt Sign And Resend Views

**Files:**
- Modify: `orders/views.py`
- Modify: `orders/urls.py`
- Test: `orders/tests.py`

**Interfaces:**
- Consumes: `OrderReceiptSignForm`, `create_signed_receipt`, `resend_receipt`
- Produces: `sign_receipt(request, order_id: int) -> HttpResponse`
- Produces: `resend_receipt_view(request, order_id: int) -> HttpResponseRedirect`
- Produces URL names `orders:sign_receipt` and `orders:resend_receipt`

- [ ] **Step 1: Write failing view tests**

Add to `orders/tests.py`:

```python
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
                    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test orders.tests.OrderReceiptViewTests -q`

Expected: FAIL because receipt URLs do not resolve.

- [ ] **Step 3: Add URL routes**

Modify `orders/urls.py`:

```python
path("<int:order_id>/receipt/sign/", views.sign_receipt, name="sign_receipt"),
path("<int:order_id>/receipt/resend/", views.resend_receipt_view, name="resend_receipt"),
```

Place these before `path('<int:order_id>/', views.get_or_create_order, name='get_order')` so the generic order route does not catch receipt paths.

- [ ] **Step 4: Add views**

Modify imports in `orders/views.py`:

```python
from django.contrib import messages
from .forms import OrderReceiptSignForm, SplitOrderForm
from .services.receipt_service import (
    ReceiptCreationError,
    create_signed_receipt,
    resend_receipt,
)
```

Add views:

```python
@login_required
@require_http_methods(["GET", "POST"])
def sign_receipt(request, order_id: int):
    order = get_object_or_404(
        Order.objects.select_related("client").prefetch_related(
            "client__contacts",
            "items__product",
            "payments",
        ),
        pk=order_id,
    )
    if order.status != OrderStatus.COMPLETED.value:
        messages.error(request, "Solo se pueden firmar recibos de pedidos completados.")
        return redirect(_get_order_redirect_url(request.user, order.client))

    if hasattr(order, "receipt"):
        messages.info(request, "Este pedido ya tiene un recibo firmado. Puede reenviarlo.")
        return redirect("orders:list")

    if request.method == "POST":
        form = OrderReceiptSignForm(request.POST, client=order.client)
        if form.is_valid():
            try:
                result = create_signed_receipt(
                    order=order,
                    cleaned_data=form.cleaned_data,
                    user=request.user,
                )
            except ReceiptCreationError as exc:
                messages.error(request, str(exc))
            else:
                if result.delivery_succeeded:
                    messages.success(request, "Recibo firmado y enviado correctamente.")
                else:
                    messages.warning(
                        request,
                        "Recibo firmado guardado, pero no se pudo enviar. Use reenviar para intentar otra vez.",
                    )
                return redirect("orders:list")
    else:
        form = OrderReceiptSignForm(client=order.client)

    return render(
        request,
        "orders/receipt_sign.html",
        {
            "order": order,
            "client": order.client,
            "contacts": list(order.client.contacts.all()),
            "form": form,
        },
    )


@login_required
@require_http_methods(["POST"])
def resend_receipt_view(request, order_id: int):
    order = get_object_or_404(
        Order.objects.select_related("client", "receipt"),
        pk=order_id,
        status=OrderStatus.COMPLETED.value,
    )
    if not hasattr(order, "receipt"):
        messages.error(request, "Este pedido no tiene un recibo firmado.")
        return redirect("orders:sign_receipt", order_id=order.pk)

    result = resend_receipt(order.receipt)
    if result.delivery_succeeded:
        messages.success(request, "Recibo reenviado correctamente.")
    else:
        messages.warning(request, "No se pudo reenviar el recibo. Intente nuevamente.")
    return redirect("orders:list")
```

- [ ] **Step 5: Run view tests**

Run: `python manage.py test orders.tests.OrderReceiptViewTests -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add orders/views.py orders/urls.py orders/tests.py
git commit -m "feat: add receipt signing views"
```

---

### Task 7: Mobile Signing Template And Canvas Script

**Files:**
- Create: `orders/templates/orders/receipt_sign.html`
- Create: `orders/static/orders/js/receipt_sign.js`
- Test: `orders/tests.py`

**Interfaces:**
- Consumes: context keys `order`, `client`, `contacts`, `form`
- Produces: hidden input `#id_signature_data`
- Produces: contact select `#id_contact_id` with data attributes used to prefill snapshot fields

- [ ] **Step 1: Write failing template smoke test**

Add to `OrderReceiptViewTests` in `orders/tests.py`:

```python
def test_sign_receipt_get_renders_form(self) -> None:
    from clients.models import Contact

    Contact.objects.create(
        client=self.customer,
        name="Ana Lopez",
        email="ana@example.com",
        phone="4421234567",
        position="Compras",
    )

    response = self.client.get(reverse("orders:sign_receipt", args=[self.order.pk]))

    self.assertEqual(response.status_code, 200)
    self.assertContains(response, "Firmar y enviar recibo")
    self.assertContains(response, "id_signature_data")
    self.assertContains(response, "receipt-signature-canvas")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test orders.tests.OrderReceiptViewTests.test_sign_receipt_get_renders_form -q`

Expected: FAIL because the template does not exist.

- [ ] **Step 3: Create signing template**

Create `orders/templates/orders/receipt_sign.html`:

```html
{% extends 'base.html' %}
{% load static %}

{% block content %}
<div class="pg-container pg-mt-4 receipt-sign-page">
  <div class="pg-flex pg-justify-between pg-align-center pg-mb-3">
    <div>
      <h1 class="pg-h4 pg-mb-1">Firmar y enviar recibo</h1>
      <p class="pg-text-muted pg-mb-0">Pedido #{{ order.pk }} - {{ client.name }}</p>
    </div>
    <a href="{% url 'orders:list' %}" class="pg-button pg-button-outline-secondary">Volver</a>
  </div>

  <form method="post" id="receipt-sign-form" class="pg-card pg-shadow-sm">
    {% csrf_token %}
    {{ form.method }}
    {{ form.signature_data }}

    <div class="pg-card-body">
      {% if contacts|length > 1 %}
        <div class="pg-mb-3">
          <label for="{{ form.contact_id.id_for_label }}" class="pg-label">Contacto</label>
          <select name="{{ form.contact_id.html_name }}" id="{{ form.contact_id.id_for_label }}" class="pg-select">
            {% for contact in contacts %}
              <option
                value="{{ contact.pk }}"
                data-name="{{ contact.name|default_if_none:'' }}"
                data-email="{{ contact.email|default_if_none:'' }}"
                data-phone="{{ contact.phone|default_if_none:'' }}"
                data-position="{{ contact.position|default_if_none:'' }}">
                {{ contact.name }} - {{ contact.email|default:"sin correo" }}
              </option>
            {% endfor %}
          </select>
        </div>
      {% else %}
        {{ form.contact_id.as_hidden }}
      {% endif %}

      <div class="pg-row pg-gap-3">
        <div class="pg-col-12 pg-col-md-6">
          <label class="pg-label" for="{{ form.contact_name.id_for_label }}">Nombre</label>
          {{ form.contact_name }}
        </div>
        <div class="pg-col-12 pg-col-md-6">
          <label class="pg-label" for="{{ form.contact_email.id_for_label }}">Correo</label>
          {{ form.contact_email }}
        </div>
        <div class="pg-col-12 pg-col-md-6">
          <label class="pg-label" for="{{ form.contact_phone.id_for_label }}">Telefono</label>
          {{ form.contact_phone }}
        </div>
        <div class="pg-col-12 pg-col-md-6">
          <label class="pg-label" for="{{ form.contact_position.id_for_label }}">Puesto</label>
          {{ form.contact_position }}
        </div>
      </div>

      <div class="pg-mt-4">
        <label class="pg-label" for="receipt-signature-canvas">Firma</label>
        <canvas id="receipt-signature-canvas" width="640" height="260" class="pg-w-100 pg-border pg-rounded"></canvas>
        <div class="pg-flex pg-gap-2 pg-mt-2">
          <button type="button" class="pg-button pg-button-outline-secondary" id="receipt-signature-clear">Limpiar</button>
          <button type="submit" class="pg-button pg-button-primary" id="receipt-submit-button">Enviar recibo</button>
        </div>
      </div>
    </div>
  </form>
</div>
{% endblock %}

{% block extra_js %}
  <script src="{% static 'orders/js/receipt_sign.js' %}"></script>
{% endblock %}
```

- [ ] **Step 4: Create canvas script**

Create `orders/static/orders/js/receipt_sign.js`:

```javascript
(function () {
  const canvas = document.getElementById('receipt-signature-canvas');
  const form = document.getElementById('receipt-sign-form');
  const signatureInput = document.getElementById('id_signature_data');
  const clearButton = document.getElementById('receipt-signature-clear');
  const contactSelect = document.getElementById('id_contact_id');

  if (!canvas || !form || !signatureInput) return;

  const context = canvas.getContext('2d');
  let drawing = false;
  let hasSignature = false;

  function pointFromEvent(event) {
    const rect = canvas.getBoundingClientRect();
    const source = event.touches ? event.touches[0] : event;
    return {
      x: (source.clientX - rect.left) * (canvas.width / rect.width),
      y: (source.clientY - rect.top) * (canvas.height / rect.height),
    };
  }

  function start(event) {
    event.preventDefault();
    drawing = true;
    const point = pointFromEvent(event);
    context.beginPath();
    context.moveTo(point.x, point.y);
  }

  function move(event) {
    if (!drawing) return;
    event.preventDefault();
    const point = pointFromEvent(event);
    context.lineWidth = 3;
    context.lineCap = 'round';
    context.strokeStyle = '#111827';
    context.lineTo(point.x, point.y);
    context.stroke();
    hasSignature = true;
  }

  function stop(event) {
    if (event) event.preventDefault();
    drawing = false;
  }

  function clearSignature() {
    context.clearRect(0, 0, canvas.width, canvas.height);
    signatureInput.value = '';
    hasSignature = false;
  }

  function fillContactFromSelection() {
    const option = contactSelect?.selectedOptions?.[0];
    if (!option) return;
    document.getElementById('id_contact_name').value = option.dataset.name || '';
    document.getElementById('id_contact_email').value = option.dataset.email || '';
    document.getElementById('id_contact_phone').value = option.dataset.phone || '';
    document.getElementById('id_contact_position').value = option.dataset.position || '';
  }

  canvas.addEventListener('mousedown', start);
  canvas.addEventListener('mousemove', move);
  window.addEventListener('mouseup', stop);
  canvas.addEventListener('touchstart', start, { passive: false });
  canvas.addEventListener('touchmove', move, { passive: false });
  canvas.addEventListener('touchend', stop, { passive: false });
  clearButton?.addEventListener('click', clearSignature);
  contactSelect?.addEventListener('change', fillContactFromSelection);
  fillContactFromSelection();

  form.addEventListener('submit', event => {
    if (!hasSignature) {
      event.preventDefault();
      window.alert('Capture la firma antes de enviar el recibo.');
      return;
    }
    signatureInput.value = canvas.toDataURL('image/png');
  });
})();
```

- [ ] **Step 5: Run template smoke test**

Run: `python manage.py test orders.tests.OrderReceiptViewTests.test_sign_receipt_get_renders_form -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add orders/templates/orders/receipt_sign.html orders/static/orders/js/receipt_sign.js orders/tests.py
git commit -m "feat: add mobile receipt signing form"
```

---

### Task 8: Create-Order Checkbox And Post-Completion Redirect

**Files:**
- Modify: `orders/templates/create_order.html`
- Modify: `orders/static/orders/js/create_order.js`
- Test: `orders/tests.py`

**Interfaces:**
- Consumes: URL name `orders:sign_receipt`
- Produces: checkbox `#receipt-sign-requested`
- Produces: `data-receipt-sign-url` on `#finish-order-btn`
- Produces: `PaymentController.shouldRedirectToReceipt() -> boolean`

- [ ] **Step 1: Write failing template test**

Add to `CreateOrderRedirectTestCase` in `orders/tests.py`:

```python
def test_order_page_renders_receipt_checkbox_and_sign_url(self) -> None:
    user = self._create_user_with_employee(username="receipt-ui", position="manager")
    self.client.force_login(user)

    response = self.client.get(reverse("orders:create_order", kwargs={"client_pk": self.customer.pk}))

    self.assertContains(response, "Firmar y enviar recibo")
    self.assertContains(response, "receipt-sign-requested")
    self.assertContains(response, reverse("orders:sign_receipt", args=[response.context["order"].pk]))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test orders.tests.CreateOrderRedirectTestCase.test_order_page_renders_receipt_checkbox_and_sign_url -q`

Expected: FAIL because the checkbox is absent.

- [ ] **Step 3: Add checkbox markup**

In `orders/templates/create_order.html`, below `#finish-order-btn`, add:

```html
<label class="pg-flex pg-align-center pg-gap-2 pg-mt-3" id="receipt-sign-requested-wrapper">
  <input
    type="checkbox"
    id="receipt-sign-requested"
    class="pg-checkbox"
    {% if order_type == 'credito' and not has_pending_credit_payment %}disabled{% endif %}>
  <span>Firmar y enviar recibo</span>
</label>
```

Add a signing URL to the finish button:

```html
data-receipt-sign-url="{% url 'orders:sign_receipt' order.pk %}"
```

- [ ] **Step 4: Update post-success redirect behavior**

In `orders/static/orders/js/create_order.js`, update `PaymentController`:

```javascript
this.receiptCheckbox = document.getElementById('receipt-sign-requested');
this.receiptSignUrl = this.finishButton?.dataset.receiptSignUrl || '';
```

Add:

```javascript
shouldRedirectToReceipt() {
  return Boolean(this.receiptCheckbox?.checked && this.receiptSignUrl);
}
```

In `handleSuccess(data)`, replace the final timeout block with:

```javascript
const redirectToReceipt = this.shouldRedirectToReceipt();
setTimeout(() => {
  if (redirectToReceipt) {
    window.location.href = this.receiptSignUrl;
    return;
  }
  navigateAfterOrderCompletion();
}, 3000);
```

Do not redirect to the receipt form from `handleCreditOrderPendingSuccess`, because those orders are not completed.

- [ ] **Step 5: Run template test**

Run: `python manage.py test orders.tests.CreateOrderRedirectTestCase.test_order_page_renders_receipt_checkbox_and_sign_url -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add orders/templates/create_order.html orders/static/orders/js/create_order.js orders/tests.py
git commit -m "feat: add receipt signing checkout redirect"
```

---

### Task 9: Completed Order Receipt Actions

**Files:**
- Modify: `orders/views.py`
- Modify: `orders/templates/orders/list_order.html`
- Modify: `orders/templates/admin/orders/pedidos_list.html`
- Modify: `clients/templates/client_detail.html`
- Test: `orders/tests.py`

**Interfaces:**
- Consumes: `order.receipt`, URL names `orders:sign_receipt`, `orders:resend_receipt`
- Produces: visible labels `Firmar recibo`, `Reintentar envio`, `Reenviar recibo`

- [ ] **Step 1: Write failing receipt action tests**

Add to `orders/tests.py`:

```python
class CompletedOrderReceiptActionTests(FastTenantTestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(username="receipt-action-user", password="testpass")
        self.client.force_login(self.user)
        self.customer = Client.objects.create(name="Action Client")
        self.order = Order.objects.create(
            client=self.customer,
            owner=self.user,
            status=OrderStatus.COMPLETED.value,
            total_amount=Decimal("45.00"),
        )

    def test_order_list_shows_sign_action_when_no_receipt_exists(self) -> None:
        response = self.client.get(reverse("orders:list"))

        self.assertContains(response, "Firmar recibo")
        self.assertContains(response, reverse("orders:sign_receipt", args=[self.order.pk]))

    def test_order_list_shows_retry_action_when_receipt_is_unsent(self) -> None:
        from orders.models import OrderReceipt, ReceiptDeliveryMethod

        OrderReceipt.objects.create(
            order=self.order,
            method=ReceiptDeliveryMethod.EMAIL,
            pdf_url="receipts/orders/1/receipt.pdf",
            contact_name="Ana Lopez",
            contact_email="ana@example.com",
            created_by=self.user,
        )

        response = self.client.get(reverse("orders:list"))

        self.assertContains(response, "Reintentar envio")
        self.assertContains(response, reverse("orders:resend_receipt", args=[self.order.pk]))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test orders.tests.CompletedOrderReceiptActionTests -q`

Expected: FAIL because receipt actions are absent.

- [ ] **Step 3: Select receipt in list querysets**

In `orders/views.py`, update `_build_orders_list_context` order queryset to include:

```python
.select_related("client", "owner", "receipt")
```

If the existing chain already calls `select_related("client", "owner")`, add `"receipt"` to that call rather than adding a duplicate query.

- [ ] **Step 4: Add list template actions**

In `orders/templates/orders/list_order.html`, inside the action button group for completed orders:

```html
{% if order.status == 'COMPLETED' %}
  {% if order.receipt %}
    <form method="post" action="{% url 'orders:resend_receipt' order.id %}" class="pg-d-inline">
      {% csrf_token %}
      <button type="submit" class="pg-button pg-button-sm pg-button-outline-info" title="{% if order.receipt.sent_at %}Reenviar recibo{% else %}Reintentar envio{% endif %}">
        <i class="fas fa-receipt"></i>
        <span class="pg-hidden pg-d-sm-inline">
          {% if order.receipt.sent_at %}Reenviar recibo{% else %}Reintentar envio{% endif %}
        </span>
      </button>
    </form>
  {% else %}
    <a href="{% url 'orders:sign_receipt' order.id %}" class="pg-button pg-button-sm pg-button-outline-info" title="Firmar recibo">
      <i class="fas fa-signature"></i>
      <span class="pg-hidden pg-d-sm-inline">Firmar recibo</span>
    </a>
  {% endif %}
{% endif %}
```

- [ ] **Step 5: Add admin order list dropdown actions**

In `orders/templates/admin/orders/pedidos_list.html`, inside each order dropdown:

```html
{% if order.status == 'COMPLETED' %}
  {% if order.receipt %}
    <li>
      <form method="post" action="{% url 'orders:resend_receipt' order.id %}">
        {% csrf_token %}
        <button type="submit" class="pg-dropdown-item">
          {% if order.receipt.sent_at %}Reenviar recibo{% else %}Reintentar envio{% endif %}
        </button>
      </form>
    </li>
  {% else %}
    <li><a class="pg-dropdown-item" href="{% url 'orders:sign_receipt' order.id %}">Firmar recibo</a></li>
  {% endif %}
{% endif %}
```

- [ ] **Step 6: Add client detail dropdown actions**

In `clients/templates/client_detail.html`, inside the completed order dropdown:

```html
{% if order.status == 'COMPLETED' %}
  {% if order.receipt %}
    <li>
      <form method="post" action="{% url 'orders:resend_receipt' order.id %}">
        {% csrf_token %}
        <button type="submit" class="pg-dropdown-item">
          {% if order.receipt.sent_at %}Reenviar recibo{% else %}Reintentar envio{% endif %}
        </button>
      </form>
    </li>
  {% else %}
    <li><a class="pg-dropdown-item" href="{% url 'orders:sign_receipt' order.id %}">Firmar recibo</a></li>
  {% endif %}
{% endif %}
```

- [ ] **Step 7: Run receipt action tests**

Run: `python manage.py test orders.tests.CompletedOrderReceiptActionTests -q`

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add orders/views.py orders/templates/orders/list_order.html orders/templates/admin/orders/pedidos_list.html clients/templates/client_detail.html orders/tests.py
git commit -m "feat: show receipt actions on completed orders"
```

---

### Task 10: Full Receipt Flow Verification

**Files:**
- Modify: files changed by Tasks 1-9 only when verification exposes a concrete defect.
- Test: `orders/tests.py`
- Validate: payment app test suite.

**Interfaces:**
- Consumes: all previous task interfaces.
- Produces: passing targeted and full order/payment test suites.

- [ ] **Step 1: Run targeted receipt tests**

Run:

```bash
python manage.py test \
  orders.tests.OrderReceiptModelTests \
  orders.tests.ReceiptStorageServiceTests \
  orders.tests.ReceiptPdfServiceTests \
  orders.tests.ReceiptDeliveryServiceTests \
  orders.tests.OrderReceiptSignFormTests \
  orders.tests.ReceiptServiceTests \
  orders.tests.OrderReceiptViewTests \
  orders.tests.CompletedOrderReceiptActionTests \
  -q
```

Expected: PASS.

- [ ] **Step 2: Run existing order tests**

Run: `python manage.py test orders -q`

Expected: PASS.

- [ ] **Step 3: Run payment tests**

Run: `python manage.py test payment -q`

Expected: PASS.

- [ ] **Step 4: Run migration check**

Run: `python manage.py makemigrations --check --dry-run`

Expected: exits with code 0 and prints `No changes detected`.

- [ ] **Step 5: Run formatting and lint when available**

Run: `make format`

Expected: formatter exits successfully.

Run: `make lint`

Expected: lint exits successfully or reports only pre-existing warnings unrelated to receipt files.

- [ ] **Step 6: Commit verification fixes**

If Step 1-5 required code fixes, commit them:

```bash
git add orders clients notification water_delivery requirements.txt payment
git commit -m "fix: stabilize order receipt flow"
```

If no fixes were required, do not create an empty commit.
