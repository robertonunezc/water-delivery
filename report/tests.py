import csv
from decimal import Decimal
from io import StringIO

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

    def test_default_report_scope_includes_own_cancelled_orders(self) -> None:
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
            _get_report_orders_queryset(self.user).values_list("id", flat=True)
        )

        self.assertIn(active_order.id, order_ids)
        self.assertIn(cancelled_order.id, order_ids)

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


class OrdersReportScopeTests(FastTenantTestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username="orders_report_owner", first_name="Ana", last_name="Reparto",
        )
        self.other_user = User.objects.create_user(username="other_report_owner")
        self.customer = Client.objects.create(name="Cliente Reporte Personal")
        self.own_orders = [
            self._create_order(self.user, status.value, Decimal(amount))
            for status, amount in [
                (OrderStatus.PENDING, "10.00"),
                (OrderStatus.COMPLETED, "20.00"),
                (OrderStatus.CANCELLED, "30.00"),
            ]
        ]
        self._create_order(self.other_user)
        self._create_order(None)
        self._create_order(self.user).delete()
        self.client.force_login(self.user)

    def _create_order(
        self,
        owner: User | None,
        status: str = OrderStatus.COMPLETED.value,
        amount: Decimal = Decimal("90.00"),
    ) -> Order:
        return Order.objects.create(
            client=self.customer, owner=owner, status=status, total_amount=amount,
        )

    def _csv_rows(self, params: dict[str, str] | None = None) -> list[list[str]]:
        response = self.client.get(reverse("report:orders_report_csv"), params)
        self.assertEqual(response.status_code, 200)
        return list(csv.reader(StringIO(response.content.decode())))

    def test_report_includes_every_own_status_and_only_own_totals(self) -> None:
        response = self.client.get(reverse("report:orders_report"))

        self.assertEqual(response.status_code, 200)
        self.assertCountEqual(response.context["orders"], self.own_orders)
        self.assertEqual(response.context["total_orders"], 3)
        self.assertEqual(
            response.context["order_stats"]["total_amount_sum"], Decimal("60.00"),
        )
        distribution = {
            row["status"]: row["count"]
            for row in response.context["status_distribution"]
        }
        self.assertEqual(distribution, {status.value: 1 for status in OrderStatus})

    def test_employee_parameter_never_changes_report_owner(self) -> None:
        for is_staff, is_superuser in [(False, False), (True, False), (True, True)]:
            self.user.is_staff = is_staff
            self.user.is_superuser = is_superuser
            self.user.save(update_fields=["is_staff", "is_superuser"])
            for employee in ["all", str(self.other_user.pk), "invalid"]:
                with self.subTest(staff=is_staff, superuser=is_superuser, employee=employee):
                    response = self.client.get(
                        reverse("report:orders_report"), {"employee": employee},
                    )
                    self.assertEqual(response.status_code, 200)
                    self.assertCountEqual(response.context["orders"], self.own_orders)
                    self.assertNotContains(response, 'name="employee"')

    def test_explicit_status_filters_still_work(self) -> None:
        for status in ["all", *(status.value for status in OrderStatus)]:
            with self.subTest(status=status):
                response = self.client.get(
                    reverse("report:orders_report"), {"status": status},
                )
                expected = [
                    order for order in self.own_orders
                    if status == "all" or order.status == status
                ]
                self.assertCountEqual(response.context["orders"], expected)

    def test_report_displays_creator_in_user_column(self) -> None:
        response = self.client.get(reverse("report:orders_report"))

        self.assertContains(response, '<th scope="col">Usuario</th>', html=True)
        self.assertContains(response, "<td>Ana Reparto</td>", html=True, count=3)

    def test_user_column_falls_back_to_username_in_report_and_csv(self) -> None:
        self.user.first_name = ""
        self.user.last_name = ""
        self.user.save(update_fields=["first_name", "last_name"])

        response = self.client.get(reverse("report:orders_report"))

        self.assertContains(
            response, "<td>orders_report_owner</td>", html=True, count=3,
        )
        rows = self._csv_rows()
        user_column = rows[0].index("Usuario")
        self.assertEqual(
            [row[user_column] for row in rows[1:]], ["orders_report_owner"] * 3,
        )

    def test_administrator_listing_still_includes_other_users_orders(self) -> None:
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])

        response = self.client.get(reverse("admin_orders"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_orders"], 5)
        self.assertTrue(any(
            order.owner_id == self.other_user.pk
            for order in response.context["orders"]
        ))

    def test_csv_owner_scope_cannot_be_overridden(self) -> None:
        self.user.is_staff = self.user.is_superuser = True
        self.user.save(update_fields=["is_staff", "is_superuser"])
        for employee in ["all", str(self.other_user.pk), "invalid"]:
            with self.subTest(employee=employee):
                rows = self._csv_rows({"employee": employee})
                self.assertCountEqual(
                    [int(row[0]) for row in rows[1:]],
                    [order.pk for order in self.own_orders],
                )

    def test_csv_includes_creator_column(self) -> None:
        rows = self._csv_rows()

        self.assertIn("Usuario", rows[0])
        user_column = rows[0].index("Usuario")
        self.assertEqual([row[user_column] for row in rows[1:]], ["Ana Reparto"] * 3)

    def test_legacy_csv_download_preserves_owner_scope(self) -> None:
        response = self.client.get(
            reverse("report:orders_report"), {"download": "csv", "employee": "all"},
        )
        rows = list(csv.reader(StringIO(response.content.decode())))

        self.assertCountEqual(
            [int(row[0]) for row in rows[1:]],
            [order.pk for order in self.own_orders],
        )
