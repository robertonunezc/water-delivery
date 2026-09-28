from datetime import date

from clients.models import Address, Client
from core.models import Transport
from tenant_client.test_utils import FastTenantTestCase

from .models import Route, RouteClient


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
