from datetime import date, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import RequestFactory
from django.urls import reverse
from django.utils import timezone
from tenant_client.test_utils import FastTenantTestCase

from clients.models import Address, Client, Contact
from core.models import Transport
from route_confirmations.models import VisitConfirmation
from route_confirmations.senders import SendReceipt
from route_confirmations.services import (
    attach_confirmation_states,
    get_next_due_visit_date,
    override_confirmation,
    record_public_response,
    send_confirmation_for_client_visit,
    send_confirmation_for_clients,
    send_next_confirmation_for_client,
    send_visit_confirmation,
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

    def test_route_client_deactivation_archives_related_confirmations(self) -> None:
        confirmation = VisitConfirmation.objects.create(
            route_client=self.route_client,
            visit_date=date(2026, 2, 23),
            token='deactivate-token',
        )

        self.route_client.is_active = False
        self.route_client.save()
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

    def test_next_due_visit_date_handles_future_anchor_date(self) -> None:
        self.route_client.anchor_date = date(2026, 5, 4)
        self.route_client.save()

        next_due = get_next_due_visit_date(
            self.route_client,
            today=date(2026, 2, 23),
        )

        self.assertEqual(next_due, date(2026, 5, 4))

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


class FakeConfirmationSender:
    def __init__(self, failed_recipients: set[str] | None = None) -> None:
        self.failed_recipients = failed_recipients or set()
        self.recipients: list[str] = []

    def send(self, message):
        self.recipients.append(message.recipient)
        if message.recipient in self.failed_recipients:
            return SendReceipt(
                recipient=message.recipient,
                channel='email',
                success=False,
                error='SMTP rejected recipient',
            )
        return SendReceipt(
            recipient=message.recipient,
            channel='email',
            success=True,
        )


class VisitConfirmationSendServiceTests(FastTenantTestCase):
    def setUp(self) -> None:
        self.client = Client.objects.create(name='Envio Confirmacion')
        Address.objects.create(
            client=self.client,
            type='delivery',
            street='Calle Envio',
        )
        self.transport = Transport.objects.create(
            license_plate='SND-001',
            model='Send Truck',
            capacity_liters=1000,
            is_active=True,
        )
        self.route = Route.objects.create(
            name='Ruta Envios',
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
        self.user = User.objects.create_user(username='sender')
        self.request = RequestFactory().get(
            '/routes/1/',
            HTTP_HOST='tenant.testserver',
        )

    def _send_with_fake(self, fake_sender: FakeConfirmationSender):
        with patch(
            'route_confirmations.services.ConfirmationSenderFactory.get_sender',
            return_value=fake_sender,
        ):
            return send_visit_confirmation(
                self.route_client,
                sent_by=self.user,
                request=self.request,
                today=date(2026, 2, 23),
            )

    def test_send_attempts_all_contact_emails(self) -> None:
        Contact.objects.create(client=self.client, name='Uno', email='uno@example.com')
        Contact.objects.create(client=self.client, name='Dos', email='dos@example.com')
        Contact.objects.create(client=self.client, name='Sin correo', email='')
        fake_sender = FakeConfirmationSender()

        result = self._send_with_fake(fake_sender)

        self.assertTrue(result.success)
        self.assertEqual(
            fake_sender.recipients,
            ['uno@example.com', 'dos@example.com'],
        )

    def test_send_without_contact_emails_fails_without_sent_record(self) -> None:
        Contact.objects.create(client=self.client, name='Sin correo', email='')
        fake_sender = FakeConfirmationSender()

        result = self._send_with_fake(fake_sender)

        self.assertFalse(result.success)
        self.assertEqual(result.outcome, 'no_recipients')
        self.assertEqual(VisitConfirmation.objects.count(), 0)
        self.assertEqual(fake_sender.recipients, [])

    def test_partial_send_success_persists_sent_confirmation_and_receipts(self) -> None:
        Contact.objects.create(client=self.client, name='Bueno', email='bueno@example.com')
        Contact.objects.create(client=self.client, name='Malo', email='malo@example.com')
        fake_sender = FakeConfirmationSender(failed_recipients={'malo@example.com'})

        result = self._send_with_fake(fake_sender)
        confirmation = VisitConfirmation.objects.get()

        self.assertTrue(result.success)
        self.assertEqual(result.outcome, 'sent')
        self.assertIsNotNone(confirmation.sent_at)
        self.assertIsNotNone(confirmation.expires_at)
        self.assertEqual(confirmation.sent_by, self.user)
        self.assertEqual(len(confirmation.receipt_log), 2)
        self.assertEqual(
            [receipt['success'] for receipt in confirmation.receipt_log],
            [True, False],
        )

    def test_all_recipient_failures_archive_unsent_confirmation(self) -> None:
        Contact.objects.create(client=self.client, name='Uno', email='uno@example.com')
        Contact.objects.create(client=self.client, name='Dos', email='dos@example.com')
        fake_sender = FakeConfirmationSender(
            failed_recipients={'uno@example.com', 'dos@example.com'}
        )

        result = self._send_with_fake(fake_sender)
        archived_confirmation = VisitConfirmation.all_objects.get()
        [self.route_client] = attach_confirmation_states(
            [self.route_client],
            today=date(2026, 2, 23),
        )

        self.assertFalse(result.success)
        self.assertEqual(result.outcome, 'send_failed')
        self.assertEqual(VisitConfirmation.objects.count(), 0)
        self.assertIsNotNone(archived_confirmation.deleted_at)
        self.assertEqual(len(archived_confirmation.receipt_log), 2)
        self.assertTrue(self.route_client.visit_confirmation_state.can_send)

    def test_expired_resend_reuses_record_and_replaces_token_and_receipts(self) -> None:
        Contact.objects.create(client=self.client, name='Uno', email='uno@example.com')
        first_sender = FakeConfirmationSender()
        first_result = self._send_with_fake(first_sender)
        confirmation = first_result.confirmation
        original_pk = confirmation.pk
        original_token = confirmation.token
        VisitConfirmation.objects.filter(pk=original_pk).update(
            expires_at=timezone.now() - timedelta(minutes=1),
            receipt_log=[{'recipient': 'old@example.com', 'success': True}],
        )

        second_sender = FakeConfirmationSender()
        second_result = self._send_with_fake(second_sender)
        confirmation.refresh_from_db()

        self.assertTrue(second_result.success)
        self.assertEqual(confirmation.pk, original_pk)
        self.assertNotEqual(confirmation.token, original_token)
        self.assertEqual(
            [receipt['recipient'] for receipt in confirmation.receipt_log],
            ['uno@example.com'],
        )

    def test_pending_non_expired_confirmation_rejects_resend(self) -> None:
        Contact.objects.create(client=self.client, name='Uno', email='uno@example.com')
        first_sender = FakeConfirmationSender()
        first_result = self._send_with_fake(first_sender)
        original_token = first_result.confirmation.token

        second_sender = FakeConfirmationSender()
        second_result = self._send_with_fake(second_sender)
        first_result.confirmation.refresh_from_db()

        self.assertFalse(second_result.success)
        self.assertEqual(second_result.outcome, 'pending')
        self.assertEqual(second_sender.recipients, [])
        self.assertEqual(first_result.confirmation.token, original_token)

    def test_successful_expired_resend_blocks_immediate_second_resend(self) -> None:
        Contact.objects.create(client=self.client, name='Uno', email='uno@example.com')
        first_result = self._send_with_fake(FakeConfirmationSender())
        VisitConfirmation.objects.filter(pk=first_result.confirmation.pk).update(
            expires_at=timezone.now() - timedelta(minutes=1),
        )
        expired_sender = FakeConfirmationSender()
        expired_result = self._send_with_fake(expired_sender)
        token_after_expired_resend = expired_result.confirmation.token

        second_sender = FakeConfirmationSender()
        second_result = self._send_with_fake(second_sender)
        expired_result.confirmation.refresh_from_db()

        self.assertTrue(expired_result.success)
        self.assertFalse(second_result.success)
        self.assertEqual(second_result.outcome, 'pending')
        self.assertEqual(second_sender.recipients, [])
        self.assertEqual(expired_result.confirmation.token, token_after_expired_resend)


class ManualVisitConfirmationTests(FastTenantTestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username='manual-confirmation',
            password='testpass123',
            is_staff=True,
        )
        self.client.force_login(self.user)
        self.transport = Transport.objects.create(
            license_plate='MNL-001',
            model='Manual Truck',
            capacity_liters=1000,
            is_active=True,
        )
        self.route = Route.objects.create(
            name='Ruta Manual',
            transportation=self.transport,
            weekday='monday',
            is_active=True,
        )
        self.request = RequestFactory().get(
            '/administrador/confirmaciones/crear/',
            HTTP_HOST='tenant.testserver',
        )

    def _create_route_client(
        self,
        *,
        client_name: str,
        email: str,
        sequence: int,
        weekday: str = 'monday',
        anchor_date: date = date(2026, 2, 23),
    ) -> RouteClient:
        client = Client.objects.create(name=client_name)
        Address.objects.create(
            client=client,
            type='delivery',
            street=f'Calle {client_name}',
        )
        Contact.objects.create(
            client=client,
            name=f'Contacto {client_name}',
            email=email,
        )
        route = self.route
        if weekday != self.route.weekday:
            route = Route.objects.create(
                name=f'Ruta {weekday}',
                transportation=self.transport,
                weekday=weekday,
                is_active=True,
            )
        return RouteClient.objects.create(
            route=route,
            client=client,
            sequence=sequence,
            interval_weeks=1,
            anchor_date=anchor_date,
            is_active=True,
        )

    def test_manual_batch_service_sends_one_confirmation_per_due_client(self) -> None:
        first_route_client = self._create_route_client(
            client_name='Cliente Manual Uno',
            email='uno@example.com',
            sequence=1,
        )
        second_route_client = self._create_route_client(
            client_name='Cliente Manual Dos',
            email='dos@example.com',
            sequence=2,
        )
        fake_sender = FakeConfirmationSender()

        with patch(
            'route_confirmations.services.ConfirmationSenderFactory.get_sender',
            return_value=fake_sender,
        ):
            results = send_confirmation_for_clients(
                [first_route_client.client, second_route_client.client],
                visit_date=date(2026, 2, 23),
                sent_by=self.user,
                request=self.request,
            )

        self.assertEqual([result.outcome for result in results], ['sent', 'sent'])
        self.assertEqual(fake_sender.recipients, ['uno@example.com', 'dos@example.com'])
        self.assertEqual(
            list(
                VisitConfirmation.objects.order_by('client__name').values_list(
                    'client',
                    'route_client',
                    'visit_date',
                )
            ),
            [
                (second_route_client.client_id, None, date(2026, 2, 23)),
                (first_route_client.client_id, None, date(2026, 2, 23)),
            ],
        )

    def test_manual_send_does_not_require_route_due_that_date(self) -> None:
        route_client = self._create_route_client(
            client_name='Cliente Martes',
            email='martes@example.com',
            sequence=1,
            weekday='tuesday',
            anchor_date=date(2026, 2, 24),
        )
        fake_sender = FakeConfirmationSender()

        with patch(
            'route_confirmations.services.ConfirmationSenderFactory.get_sender',
            return_value=fake_sender,
        ):
            result = send_confirmation_for_client_visit(
                route_client.client,
                visit_date=date(2026, 2, 23),
                sent_by=self.user,
                request=self.request,
            )

        confirmation = VisitConfirmation.objects.get()

        self.assertEqual(result.outcome, 'sent')
        self.assertTrue(result.success)
        self.assertIsNone(result.route_client)
        self.assertIsNone(confirmation.route_client)
        self.assertEqual(confirmation.client, route_client.client)
        self.assertEqual(confirmation.visit_date, date(2026, 2, 23))
        self.assertEqual(fake_sender.recipients, ['martes@example.com'])

    def test_manual_send_allows_client_without_any_route(self) -> None:
        client = Client.objects.create(name='Cliente Sin Ruta')
        Contact.objects.create(
            client=client,
            name='Contacto Sin Ruta',
            email='sin-ruta@example.com',
        )
        fake_sender = FakeConfirmationSender()

        with patch(
            'route_confirmations.services.ConfirmationSenderFactory.get_sender',
            return_value=fake_sender,
        ):
            result = send_confirmation_for_client_visit(
                client,
                visit_date=date(2026, 2, 23),
                sent_by=self.user,
                request=self.request,
            )

        confirmation = VisitConfirmation.objects.get()

        self.assertEqual(result.outcome, 'sent')
        self.assertTrue(result.success)
        self.assertIsNone(confirmation.route_client)
        self.assertEqual(confirmation.client, client)
        self.assertEqual(fake_sender.recipients, ['sin-ruta@example.com'])

    def test_send_next_confirmation_for_client_uses_next_route_day(self) -> None:
        route_client = self._create_route_client(
            client_name='Cliente Siguiente',
            email='siguiente@example.com',
            sequence=1,
        )
        fake_sender = FakeConfirmationSender()

        with patch(
            'route_confirmations.services.ConfirmationSenderFactory.get_sender',
            return_value=fake_sender,
        ):
            result = send_next_confirmation_for_client(
                route_client.client,
                sent_by=self.user,
                request=self.request,
                today=date(2026, 2, 22),
            )

        self.assertTrue(result.success)
        self.assertEqual(result.visit_date, date(2026, 2, 23))
        self.assertEqual(VisitConfirmation.objects.get().visit_date, date(2026, 2, 23))

    def test_create_confirmation_view_sends_selected_clients(self) -> None:
        first_route_client = self._create_route_client(
            client_name='Cliente Vista Uno',
            email='vista-uno@example.com',
            sequence=1,
        )
        second_route_client = self._create_route_client(
            client_name='Cliente Vista Dos',
            email='vista-dos@example.com',
            sequence=2,
        )
        fake_sender = FakeConfirmationSender()

        with patch(
            'route_confirmations.services.ConfirmationSenderFactory.get_sender',
            return_value=fake_sender,
        ):
            response = self.client.post(
                reverse('route_confirmations:create'),
                {
                    'clients': [
                        str(first_route_client.client_id),
                        str(second_route_client.client_id),
                    ],
                    'visit_date': '2026-02-23',
                },
            )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(VisitConfirmation.objects.count(), 2)
        self.assertCountEqual(
            fake_sender.recipients,
            ['vista-uno@example.com', 'vista-dos@example.com'],
        )

    def test_create_confirmation_view_sends_client_without_route(self) -> None:
        client = Client.objects.create(name='Cliente Manual Sin Ruta')
        Contact.objects.create(
            client=client,
            name='Contacto Manual Sin Ruta',
            email='manual-sin-ruta@example.com',
        )
        fake_sender = FakeConfirmationSender()

        with patch(
            'route_confirmations.services.ConfirmationSenderFactory.get_sender',
            return_value=fake_sender,
        ):
            response = self.client.post(
                reverse('route_confirmations:create'),
                {
                    'clients': [str(client.pk)],
                    'visit_date': '2026-02-23',
                },
            )

        confirmation = VisitConfirmation.objects.get()

        self.assertEqual(response.status_code, 302)
        self.assertEqual(confirmation.client, client)
        self.assertIsNone(confirmation.route_client)
        self.assertEqual(fake_sender.recipients, ['manual-sin-ruta@example.com'])

    def test_create_confirmation_view_renders_manual_form(self) -> None:
        response = self.client.get(reverse('route_confirmations:create'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Crear y enviar')

    def test_create_confirmation_view_requires_staff(self) -> None:
        route_client = self._create_route_client(
            client_name='Cliente No Staff',
            email='no-staff@example.com',
            sequence=1,
        )
        non_staff_user = User.objects.create_user(
            username='manual-confirmation-non-staff',
            password='testpass123',
        )
        self.client.force_login(non_staff_user)
        fake_sender = FakeConfirmationSender()

        with patch(
            'route_confirmations.services.ConfirmationSenderFactory.get_sender',
            return_value=fake_sender,
        ):
            response = self.client.post(
                reverse('route_confirmations:create'),
                {
                    'clients': [str(route_client.client_id)],
                    'visit_date': '2026-02-23',
                },
            )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(VisitConfirmation.objects.count(), 0)
        self.assertEqual(fake_sender.recipients, [])

    def test_client_send_next_action_creates_confirmation(self) -> None:
        route_client = self._create_route_client(
            client_name='Cliente Accion',
            email='accion@example.com',
            sequence=1,
        )
        fake_sender = FakeConfirmationSender()

        with patch(
            'route_confirmations.services.ConfirmationSenderFactory.get_sender',
            return_value=fake_sender,
        ), patch(
            'route_confirmations.services.timezone.localdate',
            return_value=date(2026, 2, 22),
        ):
            response = self.client.post(
                reverse(
                    'clients:send_next_route_confirmation',
                    args=[route_client.client_id],
                ),
                {'next': reverse('clients:detail', args=[route_client.client_id])},
            )

        self.assertEqual(response.status_code, 302)
        confirmation = VisitConfirmation.objects.get()
        self.assertEqual(confirmation.route_client, route_client)
        self.assertEqual(confirmation.visit_date, date(2026, 2, 23))

    def test_client_send_next_action_requires_staff(self) -> None:
        route_client = self._create_route_client(
            client_name='Cliente Accion No Staff',
            email='accion-no-staff@example.com',
            sequence=1,
        )
        non_staff_user = User.objects.create_user(
            username='client-confirmation-non-staff',
            password='testpass123',
        )
        self.client.force_login(non_staff_user)
        fake_sender = FakeConfirmationSender()

        with patch(
            'route_confirmations.services.ConfirmationSenderFactory.get_sender',
            return_value=fake_sender,
        ), patch(
            'route_confirmations.services.timezone.localdate',
            return_value=date(2026, 2, 22),
        ):
            response = self.client.post(
                reverse(
                    'clients:send_next_route_confirmation',
                    args=[route_client.client_id],
                ),
            )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(VisitConfirmation.objects.count(), 0)
        self.assertEqual(fake_sender.recipients, [])

    def test_client_send_next_action_rejects_inactive_client(self) -> None:
        route_client = self._create_route_client(
            client_name='Cliente Inactivo',
            email='inactivo@example.com',
            sequence=1,
        )
        route_client.client.active = False
        route_client.client.save(update_fields=['active'])
        fake_sender = FakeConfirmationSender()

        with patch(
            'route_confirmations.services.ConfirmationSenderFactory.get_sender',
            return_value=fake_sender,
        ):
            response = self.client.post(
                reverse(
                    'clients:send_next_route_confirmation',
                    args=[route_client.client_id],
                ),
            )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(VisitConfirmation.objects.count(), 0)
        self.assertEqual(fake_sender.recipients, [])

    def test_client_send_next_action_rejects_external_next_redirect(self) -> None:
        route_client = self._create_route_client(
            client_name='Cliente Next Seguro',
            email='next-seguro@example.com',
            sequence=1,
        )
        fake_sender = FakeConfirmationSender()

        with patch(
            'route_confirmations.services.ConfirmationSenderFactory.get_sender',
            return_value=fake_sender,
        ), patch(
            'route_confirmations.services.timezone.localdate',
            return_value=date(2026, 2, 22),
        ):
            response = self.client.post(
                reverse(
                    'clients:send_next_route_confirmation',
                    args=[route_client.client_id],
                ),
                {'next': 'https://example.invalid/outside'},
            )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response['Location'],
            reverse('clients:detail', args=[route_client.client_id]),
        )

    def test_confirmation_actions_are_visible_in_admin_pages(self) -> None:
        route_client = self._create_route_client(
            client_name='Cliente Botones',
            email='botones@example.com',
            sequence=1,
        )
        send_next_url = reverse(
            'clients:send_next_route_confirmation',
            args=[route_client.client_id],
        )

        confirmations_response = self.client.get(
            reverse('route_confirmations:list'),
        )
        clients_response = self.client.get(
            reverse('admin_clients'),
        )
        detail_response = self.client.get(
            reverse('clients:detail', args=[route_client.client_id]),
        )

        self.assertContains(confirmations_response, 'Crear confirmación')
        self.assertContains(clients_response, send_next_url)
        self.assertContains(detail_response, send_next_url)
