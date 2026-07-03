import csv
import io
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.urls import reverse

from clients.models import Client
from orders.models import Order, OrderProduct, OrderStatus
from payment.models import Payment
from product.models import Product, ProductCategory
from tenant_client.test_utils import FastTenantTestCase

User = get_user_model()


class BreakdownPaymentMethodReportTests(FastTenantTestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username="report_user",
            password="testpass123",
        )
        self.client.force_login(self.user)

        self.customer = Client.objects.create(
            name="Cliente Reporte",
            balance=Decimal("0.00"),
            credit_limit=Decimal("0.00"),
        )
        self.category = ProductCategory.objects.create(name="Agua")
        self.product = Product.objects.create(
            name="Garrafon",
            presentation="20",
            unit_of_measure=1,
            category=self.category,
            price=Decimal("100.00"),
        )

    def _create_order(
        self,
        *,
        subtotal: Decimal,
        discount: Decimal,
        total: Decimal,
        status: str = OrderStatus.COMPLETED.value,
        with_payment: bool = False,
        payment_status: str = "completed",
    ) -> Order:
        order = Order.objects.create(
            client=self.customer,
            owner=self.user,
            subtotal_amount=subtotal,
            discount=discount,
            total_amount=total,
            status=status,
        )
        OrderProduct.objects.create(
            order=order,
            product=self.product,
            quantity=1,
            unit_price=subtotal,
        )
        if with_payment:
            Payment.objects.create(
                amount=total,
                method="cash",
                client=self.customer,
                order=order,
                status=payment_status,
                created_by=self.user,
            )
        return order

    def test_breakdown_report_shows_discounted_orders_without_payment(self) -> None:
        discounted_order = self._create_order(
            subtotal=Decimal("100.00"),
            discount=Decimal("100.00"),
            total=Decimal("0.00"),
        )
        paid_order = self._create_order(
            subtotal=Decimal("80.00"),
            discount=Decimal("10.00"),
            total=Decimal("70.00"),
            with_payment=True,
        )

        response = self.client.get(reverse("report:breakdown_payment_method"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Descuento 100% / Sin cobro")
        self.assertContains(response, "$180.00")
        self.assertContains(response, "$110.00")
        self.assertContains(response, "$70.00")
        self.assertContains(response, "$100.00")
        self.assertContains(response, "$10.00")
        self.assertContains(response, f"#{discounted_order.id}")
        self.assertContains(response, f"#{paid_order.id}")

    def test_breakdown_report_csv_includes_discount_column_and_net_totals(self) -> None:
        self._create_order(
            subtotal=Decimal("100.00"),
            discount=Decimal("100.00"),
            total=Decimal("0.00"),
        )
        self._create_order(
            subtotal=Decimal("80.00"),
            discount=Decimal("10.00"),
            total=Decimal("70.00"),
            with_payment=True,
        )

        response = self.client.get(reverse("report:breakdown_payment_method_csv"))
        content = response.content.decode("utf-8")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Subtotal", content)
        self.assertIn("Total Descuentos", content)
        self.assertIn('"Subtotal","$180.00"', content)
        self.assertIn('"Total Descuentos","$110.00"', content)
        self.assertIn('"Monto Total","$70.00"', content)
        self.assertIn('"Método de Pago","Productos","Hora","Subtotal","Descuento","Total"', content)
        self.assertIn("Descuento 100% / Sin cobro", content)

    def test_breakdown_report_excludes_cancelled_orders_by_default(self) -> None:
        active_order = self._create_order(
            subtotal=Decimal("80.00"),
            discount=Decimal("10.00"),
            total=Decimal("70.00"),
            with_payment=True,
        )
        cancelled_order = self._create_order(
            subtotal=Decimal("60.00"),
            discount=Decimal("0.00"),
            total=Decimal("60.00"),
            status=OrderStatus.CANCELLED.value,
            with_payment=True,
        )

        response = self.client.get(reverse("report:breakdown_payment_method"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["stats"]["total_orders"], 1)
        self.assertEqual(response.context["stats"]["subtotal_amount"], Decimal("80.00"))
        cash_orders = response.context["payment_method_stats"]["cash"]["orders"]
        self.assertEqual(
            [order.id for order in cash_orders],
            [active_order.id],
        )
        self.assertNotIn(
            cancelled_order.id,
            [order.id for order in cash_orders],
        )

    def test_breakdown_csv_excludes_cancelled_orders_by_default(self) -> None:
        active_order = self._create_order(
            subtotal=Decimal("80.00"),
            discount=Decimal("10.00"),
            total=Decimal("70.00"),
            with_payment=True,
        )
        cancelled_order = self._create_order(
            subtotal=Decimal("60.00"),
            discount=Decimal("0.00"),
            total=Decimal("60.00"),
            status=OrderStatus.CANCELLED.value,
            with_payment=True,
        )

        response = self.client.get(reverse("report:breakdown_payment_method_csv"))
        content = response.content.decode("utf-8")
        rows = list(csv.reader(io.StringIO(content)))
        order_ids = {row[0] for row in rows if row and row[0].startswith("#")}

        self.assertEqual(response.status_code, 200)
        self.assertIn('"Total de Órdenes","1"', content)
        self.assertIn(f"#{active_order.id}", order_ids)
        self.assertNotIn(f"#{cancelled_order.id}", order_ids)

    def test_breakdown_report_ignores_reversed_payment_bucket(self) -> None:
        reversed_payment_order = self._create_order(
            subtotal=Decimal("50.00"),
            discount=Decimal("0.00"),
            total=Decimal("50.00"),
            with_payment=True,
            payment_status="reversed",
        )

        response = self.client.get(reverse("report:breakdown_payment_method"))
        payment_stats = response.context["payment_method_stats"]

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payment_stats["cash"]["order_count"], 0)
        self.assertEqual(payment_stats["no_payment_recorded"]["order_count"], 1)
        self.assertContains(response, "Sin pago registrado")
        self.assertContains(response, f"#{reversed_payment_order.id}")


class OrdersReportQueryTests(FastTenantTestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username="orders_report_user",
            password="testpass123",
        )
        self.client.force_login(self.user)
        self.customer = Client.objects.create(name="Cliente Orders Reporte")

    def _create_order(
        self,
        *,
        total: Decimal,
        status: str = OrderStatus.COMPLETED.value,
        payment_status: str | None = None,
    ) -> Order:
        order = Order.objects.create(
            client=self.customer,
            owner=self.user,
            subtotal_amount=total,
            total_amount=total,
            status=status,
        )
        if payment_status:
            Payment.objects.create(
                amount=total,
                method="cash",
                client=self.customer,
                order=order,
                status=payment_status,
                created_by=self.user,
            )
        return order

    def test_orders_report_excludes_cancelled_orders_by_default(self) -> None:
        active_order = self._create_order(
            total=Decimal("100.00"),
            payment_status="completed",
        )
        cancelled_order = self._create_order(
            total=Decimal("50.00"),
            status=OrderStatus.CANCELLED.value,
            payment_status="completed",
        )

        response = self.client.get(reverse("report:orders_report"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["order_stats"]["total_orders"], 1)
        page_order_ids = [order.id for order in response.context["orders"].object_list]
        self.assertEqual(page_order_ids, [active_order.id])
        self.assertNotIn(cancelled_order.id, page_order_ids)

    def test_orders_report_csv_excludes_cancelled_orders_by_default(self) -> None:
        active_order = self._create_order(
            total=Decimal("100.00"),
            payment_status="completed",
        )
        cancelled_order = self._create_order(
            total=Decimal("50.00"),
            status=OrderStatus.CANCELLED.value,
            payment_status="completed",
        )

        response = self.client.get(reverse("report:orders_report_csv"))
        content = response.content.decode("utf-8")
        rows = list(csv.reader(io.StringIO(content)))
        order_ids = {int(row[0]) for row in rows[1:] if row}

        self.assertEqual(response.status_code, 200)
        self.assertIn(active_order.id, order_ids)
        self.assertNotIn(cancelled_order.id, order_ids)

    def test_orders_report_export_link_preserves_active_filters(self) -> None:
        response = self.client.get(
            reverse("report:orders_report"),
            {
                "search": "Cliente Orders",
                "payment_method": "cash",
                "has_billing": "no",
                "sort_by": "total_amount",
                "page": "2",
            },
        )
        expected_url = (
            f'{reverse("report:orders_report_csv")}?'
            "search=Cliente+Orders&payment_method=cash&"
            "has_billing=no&sort_by=total_amount"
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'href="{expected_url.replace("&", "&amp;")}"')

    def test_payment_method_filter_ignores_reversed_payments(self) -> None:
        reversed_payment_order = self._create_order(
            total=Decimal("100.00"),
            payment_status="reversed",
        )

        response = self.client.get(
            reverse("report:orders_report"),
            {"payment_method": "cash"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["order_stats"]["total_orders"], 0)
        page_order_ids = [order.id for order in response.context["orders"].object_list]
        self.assertNotIn(reversed_payment_order.id, page_order_ids)
