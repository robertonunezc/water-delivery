from decimal import Decimal
from datetime import date, datetime, timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.urls import reverse
from django.utils import timezone

from clients.models import Address, Client
from core.models import Employee, Transport
from orders.models import Order, OrderProduct, OrderStatus
from product.models import Product
from reminders.models import Reminder
from tenant_client.test_utils import FastTenantTestCase

from .models import (
    Route,
    RouteClient,
    RouteClientOrder,
    TruckInventoryLine,
    TruckInventorySession,
)

User = get_user_model()


class RouteClientFrequencyIntervalTest(FastTenantTestCase):
    def setUp(self):
        self.delivery_client = Client.objects.create(name='Frequency Client')
        Address.objects.create(client=self.delivery_client, type='delivery', street='Calle Frecuencia')
        self.transport = Transport.objects.create(
            license_plate='XYZ-999',
            model='Test Vehicle',
            capacity_liters=1000,
            is_active=True,
        )
        self.route = Route.objects.create(
            name='Route Monday',
            transportation=self.transport,
            weekday='monday',
            is_active=True,
        )

    def test_is_due_on_every_two_weeks(self):
        route_client = RouteClient.objects.create(
            route=self.route,
            client=self.delivery_client,
            sequence=1,
            interval_weeks=2,
            anchor_date=date(2026, 3, 2),  # Monday
            is_active=True,
        )

        self.assertTrue(route_client.is_due_on(date(2026, 3, 2)))
        self.assertFalse(route_client.is_due_on(date(2026, 3, 9)))
        self.assertTrue(route_client.is_due_on(date(2026, 3, 16)))

    def test_due_on_queryset_filters_clients(self):
        RouteClient.objects.create(
            route=self.route,
            client=self.delivery_client,
            sequence=1,
            interval_weeks=1,
            anchor_date=date(2026, 3, 2),
            is_active=True,
        )

        second_client = Client.objects.create(name='Every 2 Weeks')
        Address.objects.create(client=second_client, type='delivery', street='Calle 2 semanas')
        RouteClient.objects.create(
            route=self.route,
            client=second_client,
            sequence=2,
            interval_weeks=2,
            anchor_date=date(2026, 3, 2),
            is_active=True,
        )

        due_first_week = RouteClient.objects.due_on(date(2026, 3, 2))
        due_second_week = RouteClient.objects.due_on(date(2026, 3, 9))

        self.assertEqual(due_first_week.count(), 2)
        self.assertEqual(due_second_week.count(), 1)


class RouteClientSoftDeleteTest(FastTenantTestCase):
    def setUp(self):
        self.delivery_client = Client.objects.create(name='Reactivated Route Client')
        Address.objects.create(
            client=self.delivery_client,
            type='delivery',
            street='Calle Reactivada',
        )
        self.transport = Transport.objects.create(
            license_plate='RST-001',
            model='Test Vehicle',
            capacity_liters=1000,
            is_active=True,
        )
        self.route = Route.objects.create(
            name='Route Monday',
            transportation=self.transport,
            weekday='monday',
            is_active=True,
        )

    def test_can_reassign_client_to_route_after_soft_delete(self):
        route_client = RouteClient.objects.create(
            route=self.route,
            client=self.delivery_client,
            sequence=1,
            is_active=True,
        )
        route_client.delete()

        new_route_client = RouteClient.objects.create(
            route=self.route,
            client=self.delivery_client,
            sequence=2,
            is_active=True,
        )

        self.assertEqual(new_route_client.route, self.route)
        self.assertEqual(new_route_client.client, self.delivery_client)
        self.assertEqual(
            RouteClient.objects.filter(
                route=self.route,
                client=self.delivery_client,
            ).count(),
            1,
        )
        self.assertEqual(
            RouteClient.all_objects.filter(
                route=self.route,
                client=self.delivery_client,
            ).count(),
            2,
        )


class RouteDashboardSummaryServiceTest(FastTenantTestCase):
    def setUp(self):
        self.transport = Transport.objects.create(
            license_plate='SUM-001',
            model='Summary Truck',
            capacity_liters=1000,
            is_active=True,
        )
        self.monday_route = Route.objects.create(
            name='Summary Monday',
            transportation=self.transport,
            weekday='monday',
            is_active=True,
        )
        self.tuesday_route = Route.objects.create(
            name='Summary Tuesday',
            transportation=self.transport,
            weekday='tuesday',
            is_active=True,
        )

    def _create_route_client(
        self,
        *,
        name: str,
        route: Route,
        sequence: int,
        interval_weeks: int = 1,
        is_active: bool = True,
    ) -> RouteClient:
        client = Client.objects.create(name=name)
        Address.objects.create(client=client, type='delivery', street=f'Calle {name}')
        return RouteClient.objects.create(
            route=route,
            client=client,
            sequence=sequence,
            interval_weeks=interval_weeks,
            anchor_date=date(2026, 3, 2),
            is_active=is_active,
        )

    def test_get_route_clients_due_count_uses_due_on_queryset(self):
        from routes.services import get_route_clients_due_count

        self._create_route_client(name='Due Every Week', route=self.monday_route, sequence=1)
        self._create_route_client(
            name='Not Due This Week',
            route=self.monday_route,
            sequence=2,
            interval_weeks=2,
        )
        self._create_route_client(
            name='Inactive Client',
            route=self.monday_route,
            sequence=3,
            is_active=False,
        )
        self._create_route_client(name='Different Weekday', route=self.tuesday_route, sequence=4)

        count = get_route_clients_due_count(date(2026, 3, 9))

        self.assertEqual(count, 1)


class RouteTruckInventoryModelTest(FastTenantTestCase):
    def setUp(self):
        self.transport = Transport.objects.create(
            license_plate='INV-001',
            model='Inventory Truck',
            capacity_liters=1000,
            is_active=True,
        )
        self.route = Route.objects.create(
            name='Inventory Monday',
            transportation=self.transport,
            weekday='monday',
            is_active=True,
        )
        self.product = Product.objects.create(
            name='Garrafon',
            presentation='20',
            unit_of_measure=5,
            price=50,
        )

    def _create_session(self) -> TruckInventorySession:
        return TruckInventorySession.objects.create(
            route=self.route,
            transportation=self.transport,
            service_date=date(2026, 10, 9),
        )

    def test_inventory_line_recalculates_expected_sales_difference_and_missing_containers(self):
        line = TruckInventoryLine(
            full_loaded=50,
            full_returned=10,
            empty_returned=20,
            reported_sales=35,
        )

        line.recalculate()

        self.assertEqual(line.expected_sales, 40)
        self.assertEqual(line.sales_difference, 5)
        self.assertEqual(line.missing_containers, 20)

    def test_inventory_line_rejects_negative_counts(self):
        line = TruckInventoryLine(
            session=self._create_session(),
            product=self.product,
            full_loaded=-1,
            full_returned=0,
            empty_returned=0,
        )

        with self.assertRaises(ValidationError):
            line.full_clean()

    def test_inventory_line_rejects_full_returned_greater_than_loaded(self):
        line = TruckInventoryLine(
            session=self._create_session(),
            product=self.product,
            full_loaded=10,
            full_returned=11,
            empty_returned=0,
        )

        with self.assertRaises(ValidationError):
            line.full_clean()

    def test_only_one_active_inventory_session_per_route_truck_date(self):
        self._create_session()

        with self.assertRaises(IntegrityError):
            self._create_session()

    def test_close_recalculates_and_persists_line_results(self):
        session = self._create_session()
        line = TruckInventoryLine.objects.create(
            session=session,
            product=self.product,
            full_loaded=50,
            full_returned=10,
            empty_returned=20,
            reported_sales=35,
        )

        session.close()
        line.refresh_from_db()

        self.assertEqual(session.status, TruckInventorySession.Status.CLOSED)
        self.assertEqual(line.expected_sales, 40)
        self.assertEqual(line.sales_difference, 5)
        self.assertEqual(line.missing_containers, 20)


class RouteTruckInventoryServiceTest(FastTenantTestCase):
    def setUp(self):
        self.today = date(2026, 10, 9)
        self.driver_user = User.objects.create_user(
            username='inventory-driver',
            password='testpass123',
        )
        self.staff_user = User.objects.create_user(
            username='inventory-staff',
            password='testpass123',
            is_staff=True,
        )
        self.driver = Employee.objects.create(
            user=self.driver_user,
            nombre='Inventario',
            apellidos='Chofer',
            curp='INVDRIVER000000001',
            rfc='INVDRIVER001',
            street_number='Calle 1',
            position='driver',
        )
        self.transport = Transport.objects.create(
            license_plate='INV-201',
            model='Inventory Truck',
            capacity_liters=1000,
            is_active=True,
            assigned_driver=self.driver,
        )
        self.other_transport = Transport.objects.create(
            license_plate='INV-202',
            model='Other Truck',
            capacity_liters=1000,
            is_active=True,
        )
        self.route = Route.objects.create(
            name='Inventory Friday',
            transportation=self.transport,
            weekday='friday',
            is_active=True,
        )
        self.other_route = Route.objects.create(
            name='Other Friday',
            transportation=self.other_transport,
            weekday='friday',
            is_active=True,
        )
        self.client_record = Client.objects.create(name='Inventory Client')
        self.product = Product.objects.create(
            name='Garrafon',
            presentation='20',
            unit_of_measure=5,
            price=50,
        )
        self.session = TruckInventorySession.objects.create(
            route=self.route,
            transportation=self.transport,
            service_date=self.today,
        )
        self.line = TruckInventoryLine.objects.create(
            session=self.session,
            product=self.product,
            full_loaded=10,
            full_returned=2,
            empty_returned=6,
        )
        self._create_sales_fixture()

    def _create_order(self, *, quantity: int, owner=None) -> Order:
        order = Order.objects.create(
            client=self.client_record,
            owner=owner,
            status=OrderStatus.COMPLETED.value,
            subtotal_amount=Decimal('0.00'),
            total_amount=Decimal(str(quantity * 50)),
        )
        Order.objects.filter(pk=order.pk).update(
            order_date=datetime(
                self.today.year,
                self.today.month,
                self.today.day,
                10,
                0,
                tzinfo=timezone.get_current_timezone(),
            )
        )
        OrderProduct.objects.create(
            order=order,
            product=self.product,
            quantity=quantity,
            unit_price=Decimal('50.00'),
        )
        return order

    def _create_sales_fixture(self):
        linked_driver_order = self._create_order(quantity=2, owner=self.driver_user)
        RouteClientOrder.objects.create(
            route=self.route,
            client=self.client_record,
            order=linked_driver_order,
            sequence=1,
            visit_date=self.today,
        )
        self._create_order(quantity=1, owner=self.driver_user)
        cancelled_order = self._create_order(quantity=5, owner=self.driver_user)
        cancelled_order.status = OrderStatus.CANCELLED.value
        cancelled_order.save(update_fields=['status'])

    def test_driver_inventory_routes_are_limited_to_assigned_truck(self):
        from routes.services import get_inventory_routes_for_user

        routes = get_inventory_routes_for_user(self.driver_user, self.today)

        self.assertEqual(list(routes), [self.route])

    def test_staff_inventory_routes_include_active_routes_for_date(self):
        from routes.services import get_inventory_routes_for_user

        routes = get_inventory_routes_for_user(self.staff_user, self.today)

        self.assertIn(self.route, routes)

    def test_reported_sales_counts_route_linked_and_driver_orders_once(self):
        from routes.services import get_reported_sales_by_product

        sales = get_reported_sales_by_product(
            self.route,
            self.transport,
            self.today,
        )

        self.assertEqual(sales[self.product.pk], 3)

    def test_sync_session_reported_sales_updates_line_results(self):
        from routes.services import sync_session_reported_sales

        sync_session_reported_sales(self.session)
        self.line.refresh_from_db()

        self.assertEqual(self.line.reported_sales, 3)
        self.assertEqual(self.line.sales_difference, self.line.expected_sales - 3)


class RouteTruckInventoryViewTest(FastTenantTestCase):
    def setUp(self):
        self.today = timezone.localdate()
        self.driver_user = User.objects.create_user(
            username='inventory-view-driver',
            password='testpass123',
        )
        self.staff_user = User.objects.create_user(
            username='inventory-view-staff',
            password='testpass123',
            is_staff=True,
        )
        self.driver = Employee.objects.create(
            user=self.driver_user,
            nombre='Vista',
            apellidos='Chofer',
            curp='INVVIEWDRIVER0001',
            rfc='INVVIEWDRV01',
            street_number='Calle 1',
            position='driver',
        )
        self.transport = Transport.objects.create(
            license_plate='INV-301',
            model='Inventory View Truck',
            capacity_liters=1000,
            is_active=True,
            assigned_driver=self.driver,
        )
        self.other_transport = Transport.objects.create(
            license_plate='INV-302',
            model='Other View Truck',
            capacity_liters=1000,
            is_active=True,
        )
        weekday = self.today.strftime('%A').lower()
        self.route = Route.objects.create(
            name='Inventory View Route',
            transportation=self.transport,
            weekday=weekday,
            is_active=True,
        )
        self.other_route = Route.objects.create(
            name='Other Inventory View Route',
            transportation=self.other_transport,
            weekday=weekday,
            is_active=True,
        )
        self.product = Product.objects.create(
            name='Garrafon Vista',
            presentation='20',
            unit_of_measure=5,
            price=50,
        )

    def _inventory_payload(self, *, route: Route, transportation: Transport) -> dict[str, str]:
        return {
            'service_date': self.today.isoformat(),
            'route': str(route.pk),
            'transportation': str(transportation.pk),
            'notes': 'Conteo operativo',
            'lines-TOTAL_FORMS': '1',
            'lines-INITIAL_FORMS': '0',
            'lines-MIN_NUM_FORMS': '0',
            'lines-MAX_NUM_FORMS': '1000',
            'lines-0-product': str(self.product.pk),
            'lines-0-full_loaded': '10',
            'lines-0-full_returned': '2',
            'lines-0-empty_returned': '6',
            'lines-0-notes': '',
        }

    def test_driver_get_inventory_form_preselects_single_today_route(self):
        self.client.force_login(self.driver_user)

        response = self.client.get(reverse('routes:truck_inventory'))

        self.assertContains(response, self.route.name)
        self.assertContains(response, self.transport.license_plate)

    def test_driver_cannot_post_inventory_for_other_truck(self):
        self.client.force_login(self.driver_user)

        response = self.client.post(
            reverse('routes:truck_inventory'),
            self._inventory_payload(
                route=self.other_route,
                transportation=self.other_transport,
            ),
        )

        self.assertEqual(response.status_code, 403)

    def test_staff_can_create_inventory_session_from_form(self):
        self.client.force_login(self.staff_user)

        response = self.client.post(
            reverse('routes:truck_inventory'),
            self._inventory_payload(
                route=self.route,
                transportation=self.transport,
            ),
        )

        self.assertRedirects(response, reverse('routes:truck_inventory'))
        self.assertTrue(
            TruckInventorySession.objects.filter(
                route=self.route,
                transportation=self.transport,
                service_date=self.today,
            ).exists()
        )

    def test_zero_count_product_rows_do_not_create_inventory_lines(self):
        self.client.force_login(self.staff_user)
        payload = self._inventory_payload(
            route=self.route,
            transportation=self.transport,
        )
        payload.update({
            'lines-0-full_loaded': '0',
            'lines-0-full_returned': '0',
            'lines-0-empty_returned': '0',
        })

        response = self.client.post(reverse('routes:truck_inventory'), payload)

        self.assertRedirects(response, reverse('routes:truck_inventory'))
        session = TruckInventorySession.objects.get(
            route=self.route,
            transportation=self.transport,
            service_date=self.today,
        )
        self.assertEqual(session.lines.count(), 0)


class RouteTruckInventoryIntegrationTest(FastTenantTestCase):
    def setUp(self):
        self.today = timezone.localdate()
        self.driver_user = User.objects.create_user(
            username='inventory-integration-driver',
            password='testpass123',
        )
        self.driver = Employee.objects.create(
            user=self.driver_user,
            nombre='Integracion',
            apellidos='Chofer',
            curp='INVINTDRIVER00001',
            rfc='INVINTDRV001',
            street_number='Calle 1',
            position='driver',
        )
        self.transport = Transport.objects.create(
            license_plate='INV-401',
            model='Inventory Integration Truck',
            capacity_liters=1000,
            is_active=True,
            assigned_driver=self.driver,
        )
        self.route = Route.objects.create(
            name='Inventory Integration Route',
            transportation=self.transport,
            weekday=self.today.strftime('%A').lower(),
            is_active=True,
        )

    def test_delivery_dashboard_includes_truck_inventory_action(self):
        from core.services.dashboard_service import get_delivery_dashboard_context

        context = get_delivery_dashboard_context(
            user=self.driver_user,
            today=self.today,
        )

        self.assertTrue(
            any(
                action['key'] == 'truck_inventory'
                for action in context['dashboard_actions']
            )
        )

    def test_route_detail_includes_inventory_status_link(self):
        self.client.force_login(self.driver_user)

        response = self.client.get(
            reverse('routes:detail', kwargs={'route_id': self.route.pk})
        )

        self.assertContains(response, 'Inventario de camioneta')


class RouteReminderBadgeTest(FastTenantTestCase):
    def setUp(self):
        self.today = date.today()
        self.user = User.objects.create_user(
            username='route-badge-user',
            password='testpass123',
        )
        self.other_user = User.objects.create_user(
            username='route-badge-other-user',
            password='testpass123',
        )
        self.transport = Transport.objects.create(
            license_plate='RMD-001',
            model='Reminder Truck',
            capacity_liters=1000,
            is_active=True,
        )
        self.route = Route.objects.create(
            name='Reminder Route',
            transportation=self.transport,
            weekday=self.today.strftime('%A').lower(),
            is_active=True,
        )

    def _create_route_client(self, *, name: str, sequence: int) -> RouteClient:
        client = Client.objects.create(name=name)
        Address.objects.create(client=client, type='delivery', street=f'Calle {name}')
        return RouteClient.objects.create(
            route=self.route,
            client=client,
            sequence=sequence,
            anchor_date=self.today,
            is_active=True,
        )

    def _create_employee_for_user(self) -> Employee:
        return Employee.objects.create(
            user=self.user,
            nombre='Ruta',
            apellidos='Recordatorios',
            curp='RUTAREMINDERS0012',
            rfc='RUTAREM0012',
            street_number='Calle 1',
            position='driver',
        )

    def test_route_clients_include_logged_user_active_reminder_counts(self):
        from routes.services import with_active_reminder_counts

        maria_route_client = self._create_route_client(name='Maria', sequence=1)
        jose_route_client = self._create_route_client(name='Jose', sequence=2)

        Reminder.objects.create(
            title='Recoger garrafones',
            client=maria_route_client.client,
            created_by=self.user,
        )
        Reminder.objects.create(
            title='Vender 3 garrafones',
            client=maria_route_client.client,
            reminder_date=self.today + timedelta(days=1),
            created_by=self.user,
        )
        Reminder.objects.create(
            title='Vencido no aparece',
            client=maria_route_client.client,
            reminder_date=self.today - timedelta(days=1),
            created_by=self.user,
        )
        Reminder.objects.create(
            title='Listo no aparece',
            client=maria_route_client.client,
            completed_at=timezone.now(),
            completed_by=self.user,
            created_by=self.user,
        )
        Reminder.objects.create(
            title='De otro usuario no aparece',
            client=maria_route_client.client,
            created_by=self.other_user,
        )

        route_clients = with_active_reminder_counts(
            RouteClient.objects.for_route(self.route).order_by('sequence'),
            user=self.user,
            today=self.today,
        )

        counts_by_client = {
            route_client.client_id: route_client.active_reminders_count
            for route_client in route_clients
        }
        self.assertEqual(counts_by_client[maria_route_client.client_id], 2)
        self.assertEqual(counts_by_client[jose_route_client.client_id], 0)

    def test_route_detail_links_badge_to_active_reminders_filtered_by_client(self):
        maria_route_client = self._create_route_client(name='Maria', sequence=1)
        jose_route_client = self._create_route_client(name='Jose', sequence=2)
        Reminder.objects.create(
            title='Recoger garrafones',
            client=maria_route_client.client,
            created_by=self.user,
        )
        self.client.force_login(self.user)

        response = self.client.get(
            reverse('routes:detail', kwargs={'route_id': self.route.pk})
        )

        self.assertContains(response, 'aria-label="1 recordatorios activos"')
        self.assertContains(
            response,
            f'/recordatorios/?status=activos&client={maria_route_client.client_id}',
        )
        self.assertNotContains(
            response,
            f'/recordatorios/?status=activos&client={jose_route_client.client_id}',
        )

    def test_today_route_links_badge_to_active_reminders_filtered_by_client(self):
        employee = self._create_employee_for_user()
        self.transport.assigned_driver = employee
        self.transport.save(update_fields=['assigned_driver'])
        maria_route_client = self._create_route_client(name='Maria', sequence=1)
        Reminder.objects.create(
            title='Recoger garrafones',
            client=maria_route_client.client,
            created_by=self.user,
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse('routes:today'))

        self.assertContains(response, 'aria-label="1 recordatorios activos"')
        self.assertContains(
            response,
            f'/recordatorios/?status=activos&client={maria_route_client.client_id}',
        )
