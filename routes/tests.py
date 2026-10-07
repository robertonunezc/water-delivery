from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from clients.models import Address, Client
from core.models import Employee, Transport
from reminders.models import Reminder
from tenant_client.test_utils import FastTenantTestCase

from .models import Route, RouteClient

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
