from __future__ import annotations

from typing import Any

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q, QuerySet
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from clients.models import Client

from .forms import ReminderForm
from .models import Reminder
from .services import complete_reminder, soft_delete_reminder


@login_required
def list(request):
    today = timezone.localdate()
    status = _clean_status(request.GET.get("status"))
    reminders = _filtered_reminders(
        user=request.user,
        today=today,
        status=status,
        search_query=request.GET.get("q", ""),
        client_id=request.GET.get("client", ""),
    )

    context = {
        "reminders": reminders,
        "status": status,
        "q": request.GET.get("q", "").strip(),
        "selected_client_id": request.GET.get("client", "").strip(),
        "clients": Client.objects.filter(active=True).order_by("name"),
    }
    return render(request, "reminders/list.html", context)


@login_required
def create(request):
    if request.method == "POST":
        form = ReminderForm(request.POST)
        if form.is_valid():
            reminder = form.save(commit=False)
            reminder.created_by = request.user
            reminder.save()
            messages.success(request, "Recordatorio creado correctamente.")
            return redirect("core:home")
    else:
        form = ReminderForm(initial=_create_initial_data(request.GET.get("client")))

    return render(request, "reminders/form.html", {"form": form, "is_create": True})


@login_required
def edit(request, pk: int):
    reminder = get_object_or_404(Reminder.objects.for_user(request.user), pk=pk)
    if reminder.completed_at:
        messages.warning(request, "Los recordatorios listos son de solo lectura.")
        return redirect("core:home")

    if request.method == "POST":
        form = ReminderForm(request.POST, instance=reminder)
        if form.is_valid():
            form.save()
            messages.success(request, "Recordatorio actualizado correctamente.")
            return redirect("core:home")
    else:
        form = ReminderForm(instance=reminder)

    return render(
        request,
        "reminders/form.html",
        {"form": form, "reminder": reminder, "is_create": False},
    )


@login_required
@require_POST
def complete(request, pk: int):
    reminder = get_object_or_404(Reminder.objects, pk=pk)
    complete_reminder(reminder, request.user)
    messages.success(request, "Recordatorio marcado como listo.")
    return redirect(_next_url(request))


@login_required
@require_POST
def delete(request, pk: int):
    reminder = get_object_or_404(Reminder.objects, pk=pk)
    soft_delete_reminder(reminder, request.user)
    messages.success(request, "Recordatorio eliminado correctamente.")
    return redirect(_next_url(request))


def _filtered_reminders(
    *,
    user: Any,
    today,
    status: str,
    search_query: str,
    client_id: str,
) -> QuerySet[Reminder]:
    reminders = Reminder.objects.for_user(user).select_related("client", "created_by", "completed_by")
    if status == "vencidos":
        reminders = reminders.overdue(today)
    elif status == "listos":
        reminders = reminders.completed()
    else:
        reminders = reminders.not_overdue(today)

    cleaned_query = search_query.strip()
    if cleaned_query:
        reminders = reminders.filter(
            Q(title__icontains=cleaned_query) | Q(description__icontains=cleaned_query)
        )

    cleaned_client_id = client_id.strip()
    if cleaned_client_id.isdigit():
        reminders = reminders.filter(client_id=int(cleaned_client_id))

    return reminders.urgent_first()


def _clean_status(status: str | None) -> str:
    if status in {"activos", "vencidos", "listos"}:
        return status
    return "activos"


def _create_initial_data(client_id: str | None) -> dict[str, Client]:
    if not client_id or not client_id.isdigit():
        return {}

    client = Client.objects.filter(pk=int(client_id)).first()
    if client is None:
        return {}
    return {"client": client}


def _next_url(request) -> str:
    return request.META.get("HTTP_REFERER") or reverse("reminders:list")
