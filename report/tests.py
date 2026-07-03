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
                status="completed",
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
