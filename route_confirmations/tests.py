from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.utils import timezone
from tenant_client.test_utils import FastTenantTestCase

from clients.models import Address, Client
from core.models import Transport
from route_confirmations.models import VisitConfirmation
from route_confirmations.services import (
    get_next_due_visit_date,
    override_confirmation,
    record_public_response,
)
from routes.models import Route, RouteClient

User = get_user_model()


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


class VisitConfirmationServiceTests(FastTenantTestCase):
    def setUp(self) -> None:
        self.client = Client.objects.create(name='Servicios Confirmacion')
        Address.objects.create(
            client=self.client,
            type='delivery',
            street='Calle Servicios',
        )
        self.transport = Transport.objects.create(
            license_plate='SRV-001',
            model='Service Truck',
            capacity_liters=1000,
            is_active=True,
        )
        self.route = Route.objects.create(
            name='Ruta Servicios',
            transportation=self.transport,
            weekday='monday',
            is_active=True,
        )
        self.route_client = RouteClient.objects.create(
            route=self.route,
            client=self.client,
            sequence=1,
            interval_weeks=1,
            anchor_date=date(2026, 2, 23),
            is_active=True,
        )

    def _create_confirmation(
        self,
        *,
        token: str = 'response-token',
        expires_at=None,
        status: str = VisitConfirmation.Status.SENT,
    ) -> VisitConfirmation:
        return VisitConfirmation.objects.create(
            route_client=self.route_client,
            visit_date=date(2026, 2, 23),
            token=token,
            status=status,
            sent_at=timezone.now(),
            expires_at=expires_at or timezone.now() + timedelta(hours=1),
        )

    def test_next_due_visit_date_includes_today_when_due_today(self) -> None:
        next_due = get_next_due_visit_date(
            self.route_client,
            today=date(2026, 2, 23),
        )

        self.assertEqual(next_due, date(2026, 2, 23))

    def test_next_due_visit_date_skips_to_next_valid_interval_date(self) -> None:
        self.route_client.interval_weeks = 2
        self.route_client.save()

        next_due = get_next_due_visit_date(
            self.route_client,
            today=date(2026, 3, 2),
        )

        self.assertEqual(next_due, date(2026, 3, 9))

    def test_public_confirmar_response_records_confirmed_status(self) -> None:
        confirmation = self._create_confirmation(token='confirmar-token')

        result = record_public_response('confirmar-token', 'confirmar')
        confirmation.refresh_from_db()

        self.assertEqual(result.outcome, 'recorded')
        self.assertEqual(confirmation.status, VisitConfirmation.Status.CONFIRMED)
        self.assertEqual(confirmation.public_response_action, 'confirmar')
        self.assertIsNotNone(confirmation.responded_at)

    def test_public_no_visitar_response_records_do_not_visit_status(self) -> None:
        confirmation = self._create_confirmation(token='no-visitar-token')

        result = record_public_response('no-visitar-token', 'no-visitar')
        confirmation.refresh_from_db()

        self.assertEqual(result.outcome, 'recorded')
        self.assertEqual(confirmation.status, VisitConfirmation.Status.DO_NOT_VISIT)
        self.assertEqual(confirmation.public_response_action, 'no-visitar')

    def test_expired_public_response_records_nothing(self) -> None:
        confirmation = self._create_confirmation(
            token='expired-response-token',
            expires_at=timezone.now() - timedelta(minutes=1),
        )

        result = record_public_response('expired-response-token', 'confirmar')
        confirmation.refresh_from_db()

        self.assertEqual(result.outcome, 'expired')
        self.assertEqual(confirmation.status, VisitConfirmation.Status.SENT)
        self.assertIsNone(confirmation.responded_at)

    def test_already_answered_public_response_keeps_first_decision(self) -> None:
        confirmation = self._create_confirmation(token='answered-token')
        record_public_response('answered-token', 'confirmar')

        result = record_public_response('answered-token', 'no-visitar')
        confirmation.refresh_from_db()

        self.assertEqual(result.outcome, 'already_answered')
        self.assertEqual(confirmation.status, VisitConfirmation.Status.CONFIRMED)
        self.assertEqual(confirmation.public_response_action, 'confirmar')

    def test_override_confirmation_requires_note(self) -> None:
        confirmation = self._create_confirmation(token='override-token')
        user = User.objects.create_user(username='admin')

        with self.assertRaises(ValidationError):
            override_confirmation(
                confirmation,
                VisitConfirmation.Status.DO_NOT_VISIT,
                '',
                user,
            )
