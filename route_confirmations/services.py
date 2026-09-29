from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import HttpRequest
from django.template.loader import render_to_string
from django.utils import timezone

from routes.models import RouteClient

from .models import VisitConfirmation
from .senders import ConfirmationMessage, ConfirmationSenderFactory, SendReceipt


@dataclass(frozen=True)
class ResponseResult:
    outcome: str
    confirmation: VisitConfirmation | None = None


@dataclass(frozen=True)
class SendResult:
    success: bool
    outcome: str
    confirmation: VisitConfirmation | None = None
    receipts: tuple[SendReceipt, ...] = ()
    warning_messages: tuple[str, ...] = ()


SPANISH_MONTHS = {
    1: 'Enero',
    2: 'Febrero',
    3: 'Marzo',
    4: 'Abril',
    5: 'Mayo',
    6: 'Junio',
    7: 'Julio',
    8: 'Agosto',
    9: 'Septiembre',
    10: 'Octubre',
    11: 'Noviembre',
    12: 'Diciembre',
}


def get_next_due_visit_date(route_client: RouteClient, today: date | None = None) -> date:
    current_date = today or timezone.localdate()
    max_days_to_scan = max(route_client.interval_weeks, 1) * 7 + 7

    for day_offset in range(max_days_to_scan + 1):
        candidate = current_date + timedelta(days=day_offset)
        if route_client.is_due_on(candidate):
            return candidate

    raise ValidationError('No se pudo calcular la siguiente visita del cliente.')


def get_or_create_confirmation(
    route_client: RouteClient,
    visit_date: date,
) -> VisitConfirmation:
    confirmation, _created = VisitConfirmation.objects.get_or_create(
        route_client=route_client,
        visit_date=visit_date,
        defaults={
            'status': VisitConfirmation.Status.SENT,
            'token': VisitConfirmation.generate_token(),
        },
    )
    return confirmation


def send_visit_confirmation(
    route_client: RouteClient,
    sent_by: Any,
    request: HttpRequest,
    channel: str = 'email',
    today: date | None = None,
) -> SendResult:
    recipients = _get_contact_email_recipients(route_client)
    if not recipients:
        return SendResult(success=False, outcome='no_recipients')

    visit_date = get_next_due_visit_date(route_client, today=today)
    confirmation = get_or_create_confirmation(route_client, visit_date)
    if _is_answered(confirmation):
        return SendResult(
            success=False,
            outcome='final',
            confirmation=confirmation,
        )

    if confirmation.sent_at is not None and not confirmation.can_resend():
        return SendResult(
            success=False,
            outcome='pending',
            confirmation=confirmation,
        )

    if confirmation.sent_at is not None:
        confirmation.reset_token()

    sender = ConfirmationSenderFactory.get_sender(channel)
    receipts = tuple(
        sender.send(
            _build_confirmation_message(
                confirmation=confirmation,
                recipient=recipient,
                request=request,
            )
        )
        for recipient in recipients
    )
    receipt_log = [receipt.as_dict() for receipt in receipts]
    successful_receipts = [receipt for receipt in receipts if receipt.success]
    warning_messages = tuple(
        f'{receipt.recipient}: {receipt.error}'
        for receipt in receipts
        if not receipt.success
    )

    confirmation.receipt_log = receipt_log
    if successful_receipts:
        send_time = timezone.now()
        confirmation.sent_at = send_time
        confirmation.expires_at = send_time + timedelta(hours=24)
        confirmation.sent_by = sent_by
        confirmation.status = VisitConfirmation.Status.SENT
        confirmation.save(
            update_fields=[
                'token',
                'status',
                'sent_at',
                'expires_at',
                'sent_by',
                'receipt_log',
                'updated_at',
            ]
        )
        return SendResult(
            success=True,
            outcome='sent',
            confirmation=confirmation,
            receipts=receipts,
            warning_messages=warning_messages,
        )

    confirmation.save(update_fields=['token', 'receipt_log', 'updated_at'])
    return SendResult(
        success=False,
        outcome='send_failed',
        confirmation=confirmation,
        receipts=receipts,
        warning_messages=warning_messages,
    )


def record_public_response(
    token: str,
    action: str,
    now: datetime | None = None,
) -> ResponseResult:
    response_time = now or timezone.now()
    status = _status_for_public_action(action)
    if status is None:
        return ResponseResult(outcome='invalid')

    with transaction.atomic():
        confirmation = (
            VisitConfirmation.objects.select_for_update()
            .filter(token=token)
            .first()
        )
        if confirmation is None:
            return ResponseResult(outcome='invalid')

        if _is_answered(confirmation):
            return ResponseResult(
                outcome='already_answered',
                confirmation=confirmation,
            )

        if confirmation.is_expired(response_time):
            return ResponseResult(outcome='expired', confirmation=confirmation)

        confirmation.status = status
        confirmation.responded_at = response_time
        confirmation.public_response_action = action
        confirmation.save(
            update_fields=[
                'status',
                'responded_at',
                'public_response_action',
                'updated_at',
            ]
        )

    return ResponseResult(outcome='recorded', confirmation=confirmation)


def override_confirmation(
    confirmation: VisitConfirmation,
    status: str,
    note: str,
    user: Any,
) -> VisitConfirmation:
    cleaned_note = note.strip()
    if not cleaned_note:
        raise ValidationError('La nota de ajuste es obligatoria.')

    if status not in VisitConfirmation.Status.values:
        raise ValidationError('Estatus de confirmación inválido.')

    with transaction.atomic():
        locked_confirmation = VisitConfirmation.objects.select_for_update().get(
            pk=confirmation.pk
        )
        locked_confirmation.status = status
        locked_confirmation.override_note = cleaned_note
        locked_confirmation.responded_by = user
        locked_confirmation.responded_at = timezone.now()
        locked_confirmation.public_response_action = None
        locked_confirmation.save(
            update_fields=[
                'status',
                'override_note',
                'responded_by',
                'responded_at',
                'public_response_action',
                'updated_at',
            ]
        )
        return locked_confirmation


def _status_for_public_action(action: str) -> str | None:
    if action == VisitConfirmation.PublicAction.CONFIRM:
        return VisitConfirmation.Status.CONFIRMED
    if action == VisitConfirmation.PublicAction.DO_NOT_VISIT:
        return VisitConfirmation.Status.DO_NOT_VISIT
    return None


def _is_answered(confirmation: VisitConfirmation) -> bool:
    return (
        confirmation.responded_at is not None
        or confirmation.status != VisitConfirmation.Status.SENT
    )


def _get_contact_email_recipients(route_client: RouteClient) -> list[str]:
    return list(
        route_client.client.contacts.exclude(email__isnull=True)
        .exclude(email='')
        .order_by('id')
        .values_list('email', flat=True)
    )


def _build_confirmation_message(
    *,
    confirmation: VisitConfirmation,
    recipient: str,
    request: HttpRequest,
) -> ConfirmationMessage:
    visit_date = format_visit_date(confirmation.visit_date)
    confirm_url = _build_public_action_url(
        request,
        confirmation.token,
        VisitConfirmation.PublicAction.CONFIRM,
    )
    do_not_visit_url = _build_public_action_url(
        request,
        confirmation.token,
        VisitConfirmation.PublicAction.DO_NOT_VISIT,
    )
    subject = f'Confirma tu visita de {visit_date} de entrega de garrafones de agua'
    body = render_to_string(
        'route_confirmations/email/visit_confirmation.txt',
        {
            'client_name': confirmation.route_client.client.name,
            'visit_date': visit_date,
            'confirm_url': confirm_url,
            'do_not_visit_url': do_not_visit_url,
        },
    )
    return ConfirmationMessage(
        recipient=recipient,
        subject=subject,
        body=body,
        client_name=confirmation.route_client.client.name,
        visit_date=visit_date,
        confirm_url=confirm_url,
        do_not_visit_url=do_not_visit_url,
    )


def _build_public_action_url(request: HttpRequest, token: str, action: str) -> str:
    path = f'/confirmaciones/visita/{token}/{action}/'
    return request.build_absolute_uri(path)


def format_visit_date(visit_date: date) -> str:
    return f'{visit_date.day} {SPANISH_MONTHS[visit_date.month]} {visit_date.year}'
