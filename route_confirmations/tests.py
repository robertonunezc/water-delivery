from datetime import date, timedelta

from django.db import IntegrityError
from django.utils import timezone
from tenant_client.test_utils import FastTenantTestCase

from clients.models import Address, Client
from core.models import Transport
from route_confirmations.models import VisitConfirmation
from routes.models import Route, RouteClient


class VisitConfirmationModelTests(FastTenantTestCase):
    def setUp(self) -> None:
        self.client = Client.objects.create(name='Confirmacion Cliente')
        Address.objects.create(
            client=self.client,
            type='delivery',
            street='Calle Confirmacion',
        )
        self.transport = Transport.objects.create(
            license_plate='CNF-001',
            model='Confirmation Truck',
            capacity_liters=1000,
            is_active=True,
        )
        self.route = Route.objects.create(
            name='Ruta Confirmaciones',
            transportation=self.transport,
            weekday='monday',
            is_active=True,
        )
        self.route_client = RouteClient.objects.create(
            route=self.route,
            client=self.client,
            sequence=1,
            anchor_date=date(2026, 2, 23),
            is_active=True,
        )

    def test_active_confirmation_is_unique_by_route_client_and_visit_date(self) -> None:
        VisitConfirmation.objects.create(
            route_client=self.route_client,
            visit_date=date(2026, 2, 23),
            token='first-token',
        )

        with self.assertRaises(IntegrityError):
            VisitConfirmation.objects.create(
                route_client=self.route_client,
                visit_date=date(2026, 2, 23),
                token='second-token',
            )

    def test_display_status_shows_expired_for_pending_expired_confirmation(self) -> None:
        confirmation = VisitConfirmation.objects.create(
            route_client=self.route_client,
            visit_date=date(2026, 2, 23),
            token='expired-token',
            status=VisitConfirmation.Status.SENT,
            expires_at=timezone.now() - timedelta(minutes=1),
        )

        self.assertEqual(confirmation.display_status(), 'Expirada')

    def test_route_client_delete_archives_related_confirmations(self) -> None:
        confirmation = VisitConfirmation.objects.create(
            route_client=self.route_client,
            visit_date=date(2026, 2, 23),
            token='archive-token',
        )

        self.route_client.delete()
        confirmation.refresh_from_db()

        self.assertIsNotNone(confirmation.deleted_at)
        self.assertFalse(
            VisitConfirmation.objects.filter(pk=confirmation.pk).exists()
        )
