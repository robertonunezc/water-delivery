from __future__ import annotations

from datetime import date
from typing import Any

from django.core.exceptions import PermissionDenied
from django.utils import timezone
from core.models import Transport
from routes.models import Route, RouteClient

from .models import Reminder


def get_user_route_client_ids(user: Any, target_date: date | None = None) -> set[int]:
    """Return due client IDs in the logged-in user's assigned route for today."""
    current_date = target_date or timezone.localdate()
    employee = getattr(user, "employee", None)
    if employee is None:
        return set()

    transportation = Transport.objects.filter(assigned_driver=employee, is_active=True).first()
    if transportation is None:
        return set()

    today_route = Route.objects.filter(
        transportation=transportation,
        weekday=current_date.strftime("%A").lower(),
        is_active=True,
    ).first()
    if today_route is None:
        return set()

    return set(
        RouteClient.objects.due_on(current_date)
        .filter(route=today_route)
        .values_list("client_id", flat=True)
    )


def get_home_reminder_context(user: Any, today: date | None = None) -> dict[str, list[Reminder]]:
    """Return reminder groups shown on the home dashboard."""
    current_date = today or timezone.localdate()
    route_client_ids = get_user_route_client_ids(user, current_date)
    today_reminders: list[Reminder] = []
    route_context_reminders: list[Reminder] = []

    reminders = (
        Reminder.objects.for_user(user)
        .active()
        .select_related("client", "created_by", "completed_by")
        .urgent_first()
    )

    for reminder in reminders:
        client_in_route = reminder.client_id in route_client_ids if reminder.client_id else False
        if _belongs_in_today_group(reminder, current_date, client_in_route):
            today_reminders.append(reminder)
        elif _belongs_in_route_context_group(reminder, current_date, client_in_route):
            route_context_reminders.append(reminder)

    return {
        "today_reminders": sorted(today_reminders, key=lambda reminder: _today_sort_key(reminder, current_date)),
        "route_context_reminders": sorted(route_context_reminders, key=_future_route_sort_key),
    }


def complete_reminder(reminder: Reminder, user: Any) -> Reminder:
    """Mark a reminder as completed after confirming ownership."""
    _ensure_owner(reminder, user)
    reminder.mark_completed(user)
    return reminder


def soft_delete_reminder(reminder: Reminder, user: Any) -> None:
    """Soft-delete a reminder after confirming ownership."""
    _ensure_owner(reminder, user)
    reminder.delete()


def _belongs_in_today_group(reminder: Reminder, current_date: date, client_in_route: bool) -> bool:
    if reminder.reminder_date == current_date:
        return True
    if reminder.reminder_date is not None:
        return False
    return reminder.client_id is None or client_in_route


def _belongs_in_route_context_group(
    reminder: Reminder,
    current_date: date,
    client_in_route: bool,
) -> bool:
    return (
        client_in_route
        and reminder.reminder_date is not None
        and reminder.reminder_date > current_date
    )


def _today_sort_key(reminder: Reminder, current_date: date) -> tuple[bool, int, date, Any, int]:
    if reminder.reminder_date == current_date:
        group_rank = 0
    elif reminder.client_id is not None:
        group_rank = 1
    else:
        group_rank = 2

    return (
        not reminder.urgent,
        group_rank,
        reminder.reminder_date or date.max,
        reminder.created_at or timezone.now(),
        reminder.pk or 0,
    )


def _future_route_sort_key(reminder: Reminder) -> tuple[bool, date, Any, int]:
    return (
        not reminder.urgent,
        reminder.reminder_date or date.max,
        reminder.created_at or timezone.now(),
        reminder.pk or 0,
    )


def _ensure_owner(reminder: Reminder, user: Any) -> None:
    if reminder.created_by_id != user.id:
        raise PermissionDenied("No tienes permiso para modificar este recordatorio.")
