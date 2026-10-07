from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Iterable

from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import HttpRequest
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from clients.models import Client
from routes.models import WEEKDAY_TO_INDEX, RouteClient

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


@dataclass(frozen=True)
class RouteClientConfirmationState:
    visit_date: date
    confirmation: VisitConfirmation | None
    display_status: str
    badge_class: str
    action_label: str
    can_send: bool


@dataclass(frozen=True)
class ClientConfirmationSendResult:
    client: Client
    outcome: str
    route_client: RouteClient | None = None
    visit_date: date | None = None
    send_result: SendResult | None = None

    @property
    def success(self) -> bool:
        return bool(self.send_result and self.send_result.success)


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
    if not route_client.route_id or not route_client.is_active:
        raise ValidationError('No se pudo calcular la siguiente visita del cliente.')

    anchor_date = _aligned_anchor_date(route_client)
    if current_date <= anchor_date:
        return anchor_date

    period_days = max(route_client.interval_weeks, 1) * 7
    days_since_anchor = (current_date - anchor_date).days
    periods_since_anchor = (days_since_anchor + period_days - 1) // period_days
    return anchor_date + timedelta(days=periods_since_anchor * period_days)


def _aligned_anchor_date(route_client: RouteClient) -> date:
    route_weekday_index = WEEKDAY_TO_INDEX.get(route_client.route.weekday)
    if route_weekday_index is None:
        raise ValidationError('No se pudo calcular la siguiente visita del cliente.')

    weekday_delta = (route_client.anchor_date.weekday() - route_weekday_index) % 7
    return route_client.anchor_date - timedelta(days=weekday_delta)


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
    recipients = _get_client_email_recipients(route_client.client)
    if not recipients:
        return SendResult(success=False, outcome='no_recipients')

    visit_date = get_next_due_visit_date(route_client, today=today)
    with transaction.atomic():
        confirmation = _get_or_create_confirmation_for_update(route_client, visit_date)
        return _send_confirmation(
            confirmation=confirmation,
            recipients=recipients,
            sent_by=sent_by,
            request=request,
            channel=channel,
        )


def send_confirmation_for_clients(
    clients: Iterable[Client],
    *,
    visit_date: date,
    sent_by: Any,
    request: HttpRequest,
    channel: str = 'email',
) -> tuple[ClientConfirmationSendResult, ...]:
    return tuple(
        send_confirmation_for_client_visit(
            client,
            visit_date=visit_date,
            sent_by=sent_by,
            request=request,
            channel=channel,
        )
        for client in clients
    )


def send_confirmation_for_client_visit(
    client: Client,
    *,
    visit_date: date,
    sent_by: Any,
    request: HttpRequest,
    channel: str = 'email',
) -> ClientConfirmationSendResult:
    send_result = send_manual_visit_confirmation(
        client,
        visit_date=visit_date,
        sent_by=sent_by,
        request=request,
        channel=channel,
    )
    return ClientConfirmationSendResult(
        client=client,
        outcome=send_result.outcome,
        route_client=(
            send_result.confirmation.route_client
            if send_result.confirmation
            else None
        ),
        visit_date=visit_date,
        send_result=send_result,
    )


def send_manual_visit_confirmation(
    client: Client,
    *,
    visit_date: date,
    sent_by: Any,
    request: HttpRequest,
    channel: str = 'email',
) -> SendResult:
    recipients = _get_client_email_recipients(client)
    if not recipients:
        return SendResult(success=False, outcome='no_recipients')

    with transaction.atomic():
        confirmation = _get_or_create_manual_confirmation_for_update(
            client,
            visit_date,
        )
        return _send_confirmation(
            confirmation=confirmation,
            recipients=recipients,
            sent_by=sent_by,
            request=request,
            channel=channel,
        )


def send_next_confirmation_for_client(
    client: Client,
    *,
    sent_by: Any,
    request: HttpRequest,
    channel: str = 'email',
    today: date | None = None,
) -> ClientConfirmationSendResult:
    next_visit = get_next_route_client_visit_for_client(client, today=today)
    if next_visit is None:
        return ClientConfirmationSendResult(client=client, outcome='no_route_client')

    route_client, visit_date = next_visit
    send_result = send_visit_confirmation(
        route_client,
        sent_by=sent_by,
        request=request,
        channel=channel,
        today=visit_date,
    )
    return ClientConfirmationSendResult(
        client=client,
        outcome=send_result.outcome,
        route_client=route_client,
        visit_date=visit_date,
        send_result=send_result,
    )


def get_due_route_client_for_client(
    client: Client,
    visit_date: date,
) -> RouteClient | None:
    return (
        RouteClient.objects.filter(client=client, route__is_active=True)
        .due_on(visit_date)
        .select_related('route', 'client')
        .order_by('sequence', 'route_id', 'id')
        .first()
    )


def get_next_route_client_visit_for_client(
    client: Client,
    today: date | None = None,
) -> tuple[RouteClient, date] | None:
    route_clients = (
        RouteClient.objects.filter(
            client=client,
            is_active=True,
            route__is_active=True,
        )
        .select_related('route', 'client')
        .order_by('sequence', 'route_id', 'id')
    )
    best_visit: tuple[date, int, int, int, RouteClient] | None = None
    for route_client in route_clients:
        try:
            visit_date = get_next_due_visit_date(route_client, today=today)
        except ValidationError:
            continue
        candidate = (
            visit_date,
            route_client.sequence,
            route_client.route_id or 0,
            route_client.pk or 0,
            route_client,
        )
        if best_visit is None or candidate[:4] < best_visit[:4]:
            best_visit = candidate

    if best_visit is None:
        return None
    return best_visit[4], best_visit[0]


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


def _get_or_create_confirmation_for_update(
    route_client: RouteClient,
    visit_date: date,
) -> VisitConfirmation:
    confirmation = (
        VisitConfirmation.objects.select_for_update()
        .filter(route_client=route_client, visit_date=visit_date)
        .first()
    )
    if confirmation is not None:
        return confirmation

    return VisitConfirmation(
        route_client=route_client,
        client=route_client.client,
        visit_date=visit_date,
        status=VisitConfirmation.Status.SENT,
        token=VisitConfirmation.generate_token(),
    )


def _get_or_create_manual_confirmation_for_update(
    client: Client,
    visit_date: date,
) -> VisitConfirmation:
    confirmation = (
        VisitConfirmation.objects.select_for_update()
        .filter(
            client=client,
            route_client__isnull=True,
            visit_date=visit_date,
        )
        .first()
    )
    if confirmation is not None:
        return confirmation

    return VisitConfirmation(
        client=client,
        visit_date=visit_date,
        status=VisitConfirmation.Status.SENT,
        token=VisitConfirmation.generate_token(),
    )


def _send_confirmation(
    *,
    confirmation: VisitConfirmation,
    recipients: list[str],
    sent_by: Any,
    request: HttpRequest,
    channel: str,
) -> SendResult:
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
    if confirmation.pk is None:
        confirmation.save()

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

    confirmation.deleted_at = timezone.now()
    confirmation.save(
        update_fields=['token', 'receipt_log', 'deleted_at', 'updated_at']
    )
    return SendResult(
        success=False,
        outcome='send_failed',
        confirmation=confirmation,
        receipts=receipts,
        warning_messages=warning_messages,
    )


def _get_client_email_recipients(client: Client) -> list[str]:
    return list(
        client.contacts.exclude(email__isnull=True)
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
        VisitConfirmation.PublicAction.CONFIRM.value,
    )
    do_not_visit_url = _build_public_action_url(
        request,
        confirmation.token,
        VisitConfirmation.PublicAction.DO_NOT_VISIT.value,
    )
    subject = f'Confirma tu visita de {visit_date} de entrega de garrafones de agua'
    body = render_to_string(
        'route_confirmations/email/visit_confirmation.txt',
        {
            'client_name': confirmation.client.name,
            'visit_date': visit_date,
            'confirm_url': confirm_url,
            'do_not_visit_url': do_not_visit_url,
        },
    )
    return ConfirmationMessage(
        recipient=recipient,
        subject=subject,
        body=body,
        client_name=confirmation.client.name,
        visit_date=visit_date,
        confirm_url=confirm_url,
        do_not_visit_url=do_not_visit_url,
    )


def _build_public_action_url(request: HttpRequest, token: str, action: str) -> str:
    path = reverse(
        'route_confirmations:respond',
        kwargs={'token': token, 'action': action},
    )
    return request.build_absolute_uri(path)


def format_visit_date(visit_date: date) -> str:
    return f'{visit_date.day} {SPANISH_MONTHS[visit_date.month]} {visit_date.year}'


def attach_confirmation_states(
    route_clients: list[RouteClient],
    today: date | None = None,
) -> list[RouteClient]:
    for route_client in route_clients:
        visit_date = get_next_due_visit_date(route_client, today=today)
        confirmation = VisitConfirmation.objects.filter(
            route_client=route_client,
            visit_date=visit_date,
        ).first()
        route_client.visit_confirmation_state = _build_route_client_state(
            visit_date,
            confirmation,
        )
    return route_clients


def _build_route_client_state(
    visit_date: date,
    confirmation: VisitConfirmation | None,
) -> RouteClientConfirmationState:
    if confirmation is None:
        return RouteClientConfirmationState(
            visit_date=visit_date,
            confirmation=None,
            display_status='Sin enviar',
            badge_class='pg-bg-secondary',
            action_label='Enviar confirmación',
            can_send=True,
        )

    display_status = confirmation.display_status()
    if display_status == 'Expirada':
        return RouteClientConfirmationState(
            visit_date=visit_date,
            confirmation=confirmation,
            display_status=display_status,
            badge_class='pg-bg-warning',
            action_label='Enviar de nuevo',
            can_send=True,
        )

    badge_class = {
        VisitConfirmation.Status.SENT: 'pg-bg-info',
        VisitConfirmation.Status.CONFIRMED: 'pg-bg-success',
        VisitConfirmation.Status.DO_NOT_VISIT: 'pg-bg-danger',
    }.get(confirmation.status, 'pg-bg-secondary')
    action_label = (
        'Enviar de nuevo'
        if confirmation.status == VisitConfirmation.Status.SENT
        else display_status
    )
    return RouteClientConfirmationState(
        visit_date=visit_date,
        confirmation=confirmation,
        display_status=display_status,
        badge_class=badge_class,
        action_label=action_label,
        can_send=False,
    )
