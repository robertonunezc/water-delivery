from __future__ import annotations

from datetime import date
from typing import Any

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from core.models import TimeStampedModel


class ReminderQuerySet(models.QuerySet):
    def for_user(self, user: Any) -> "ReminderQuerySet":
        return self.filter(created_by=user)

    def active(self) -> "ReminderQuerySet":
        return self.filter(completed_at__isnull=True)

    def completed(self) -> "ReminderQuerySet":
        return self.filter(completed_at__isnull=False)

    def overdue(self, today: date) -> "ReminderQuerySet":
        return self.active().filter(reminder_date__lt=today)

    def not_overdue(self, today: date) -> "ReminderQuerySet":
        return self.active().filter(
            Q(reminder_date__isnull=True) | Q(reminder_date__gte=today)
        )

    def urgent_first(self) -> "ReminderQuerySet":
        return self.order_by("-urgent", "reminder_date", "created_at", "id")


class ReminderManager(models.Manager.from_queryset(ReminderQuerySet)):
    def get_queryset(self) -> ReminderQuerySet:
        return super().get_queryset().filter(deleted_at=None)


class ReminderAllObjectsManager(models.Manager.from_queryset(ReminderQuerySet)):
    pass


class Reminder(TimeStampedModel):
    title = models.CharField(max_length=255, verbose_name="Titulo")
    description = models.TextField(blank=True, verbose_name="Descripcion")
    client = models.ForeignKey(
        "clients.Client",
        related_name="reminders",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Cliente",
    )
    reminder_date = models.DateField(
        null=True,
        blank=True,
        verbose_name="Fecha",
    )
    urgent = models.BooleanField(default=False, verbose_name="Urgente")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="reminders",
        on_delete=models.CASCADE,
        verbose_name="Creado por",
    )
    completed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Completado en",
    )
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="completed_reminders",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Completado por",
    )

    objects = ReminderManager()
    all_objects = ReminderAllObjectsManager()

    class Meta:
        verbose_name = "Recordatorio"
        verbose_name_plural = "Recordatorios"
        ordering = ["-urgent", "reminder_date", "created_at", "id"]
        indexes = [
            models.Index(fields=["created_by", "completed_at"], name="rem_user_done_idx"),
            models.Index(fields=["reminder_date"], name="rem_date_idx"),
            models.Index(fields=["urgent"], name="rem_urgent_idx"),
        ]

    def __str__(self) -> str:
        return self.title

    def mark_completed(
        self,
        user: Any,
        completed_at: timezone.datetime | None = None,
    ) -> None:
        if self.completed_at:
            return

        self.completed_at = completed_at or timezone.now()
        self.completed_by = user
        self.save(update_fields=["completed_at", "completed_by", "updated_at"])
