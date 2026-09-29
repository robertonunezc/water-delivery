from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from routes.models import RouteClient

from .models import VisitConfirmation


@dataclass(frozen=True)
class ResponseResult:
    outcome: str
    confirmation: VisitConfirmation | None = None


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
