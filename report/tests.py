from decimal import Decimal

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from clients.models import Client
from core.models import Transport
from orders.models import Order, OrderProduct, OrderStatus
from payment.models import Payment
from product.models import Product, ProductCategory
from report.views import (
    FULL_DISCOUNT_METHOD,
    NO_PAYMENT_RECORDED_METHOD,
    _get_breakdown_order_stats,
    _get_order_payment_bucket,
    _get_payment_method_order_ids,
    _get_report_orders_queryset,
)
from routes.models import Route, TruckInventoryLine, TruckInventorySession
from tenant_client.test_utils import FastTenantTestCase


User = get_user_model()


class ReportBusinessRuleTests(FastTenantTestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(username="report_user")
        self.customer = Client.objects.create(name="Cliente Reporte")
        category = ProductCategory.objects.create(name="Agua")
        self.product = Product.objects.create(
            name="Garrafon",
            presentation="20",
            unit_of_measure=1,
            category=category,
            price=Decimal("100.00"),
        )

    def _create_order(
        self,
        *,
        subtotal: Decimal,
        discount: Decimal = Decimal("0.00"),
        total: Decimal,
        status: str = OrderStatus.COMPLETED.value,
        payment_status: str | None = None,
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

    def test_breakdown_uses_net_totals_and_full_discount_bucket(self) -> None:
        discounted_order = self._create_order(
            subtotal=Decimal("100.00"),
            discount=Decimal("100.00"),
            total=Decimal("0.00"),
        )
        self._create_order(
            subtotal=Decimal("80.00"),
            discount=Decimal("10.00"),
            total=Decimal("70.00"),
            payment_status="completed",
        )

        stats = _get_breakdown_order_stats(Order.objects.active())

        self.assertEqual(stats["subtotal_amount"], Decimal("180.00"))
        self.assertEqual(stats["total_discount"], Decimal("110.00"))
        self.assertEqual(stats["total_amount"], Decimal("70.00"))
        self.assertEqual(
            _get_order_payment_bucket(discounted_order)[0],
            FULL_DISCOUNT_METHOD,
        )

    def test_default_report_scope_excludes_cancelled_orders(self) -> None:
        active_order = self._create_order(
            subtotal=Decimal("80.00"),
            total=Decimal("80.00"),
        )
        cancelled_order = self._create_order(
            subtotal=Decimal("60.00"),
            total=Decimal("60.00"),
            status=OrderStatus.CANCELLED.value,
        )

        order_ids = set(
            _get_report_orders_queryset().values_list("id", flat=True)
        )

        self.assertIn(active_order.id, order_ids)
        self.assertNotIn(cancelled_order.id, order_ids)

    def test_reversed_payment_is_not_a_report_payment(self) -> None:
        order = self._create_order(
            subtotal=Decimal("50.00"),
            total=Decimal("50.00"),
            payment_status="reversed",
        )

        bucket, _ = _get_order_payment_bucket(order)
        cash_order_ids = set(
            _get_payment_method_order_ids("cash").values_list("order_id", flat=True)
        )

        self.assertEqual(bucket, NO_PAYMENT_RECORDED_METHOD)
        self.assertNotIn(order.id, cash_order_ids)

    def test_daily_report_includes_inventory_summary(self) -> None:
        selected_date = timezone.localdate()
        staff_user = User.objects.create_user(
            username="inventory_report_staff",
            is_staff=True,
        )
        transport = Transport.objects.create(
            license_plate="INV-501",
            model="Report Truck",
            capacity_liters=1000,
            is_active=True,
        )
        route = Route.objects.create(
            name="Report Inventory Route",
            transportation=transport,
            weekday=selected_date.strftime("%A").lower(),
            is_active=True,
        )
        session = TruckInventorySession.objects.create(
            route=route,
            transportation=transport,
            service_date=selected_date,
        )
        TruckInventoryLine.objects.create(
            session=session,
            product=self.product,
            full_loaded=10,
            full_returned=2,
            empty_returned=6,
            expected_sales=8,
            reported_sales=7,
            sales_difference=1,
            missing_containers=2,
        )
        self._create_order(
            subtotal=Decimal("80.00"),
            total=Decimal("80.00"),
            payment_status="completed",
        )
        self.client.force_login(staff_user)

        response = self.client.get(
            reverse("report:breakdown_payment_method"),
            {"date": selected_date.isoformat()},
        )

        self.assertContains(response, "Cuadre de camionetas")
        self.assertContains(response, transport.license_plate)
