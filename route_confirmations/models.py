import secrets
from datetime import datetime

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from core.models import TimeStampedModel


def generate_confirmation_token() -> str:
    return secrets.token_urlsafe(32)


class VisitConfirmation(TimeStampedModel):
    class Status(models.TextChoices):
        SENT = 'Enviada', 'Enviada'
        CONFIRMED = 'Confirmada', 'Confirmada'
        DO_NOT_VISIT = 'NO visitar', 'NO visitar'

    class PublicAction(models.TextChoices):
        CONFIRM = 'confirmar', 'Confirmar'
        DO_NOT_VISIT = 'no-visitar', 'No visitar'

    route_client = models.ForeignKey(
        'routes.RouteClient',
        related_name='visit_confirmations',
        on_delete=models.CASCADE,
        verbose_name='Cliente en ruta',
    )
    visit_date = models.DateField(verbose_name='Fecha de visita')
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.SENT,
        verbose_name='Estatus',
    )
    token = models.CharField(
        max_length=128,
        unique=True,
        db_index=True,
        default=generate_confirmation_token,
        verbose_name='Token',
    )
    sent_at = models.DateTimeField(null=True, blank=True, verbose_name='Enviado')
    expires_at = models.DateTimeField(null=True, blank=True, verbose_name='Expira')
    responded_at = models.DateTimeField(null=True, blank=True, verbose_name='Respondido')
    public_response_action = models.CharField(
        max_length=20,
        choices=PublicAction.choices,
        blank=True,
        null=True,
        verbose_name='Acción pública',
    )
    sent_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name='sent_visit_confirmations',
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        verbose_name='Enviado por',
    )
    responded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name='overridden_visit_confirmations',
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        verbose_name='Respondido por',
    )
    override_note = models.TextField(blank=True, verbose_name='Nota de ajuste')
    receipt_log = models.JSONField(default=list, blank=True, verbose_name='Recibos')

    class Meta:
        verbose_name = 'Confirmación de visita'
        verbose_name_plural = 'Confirmaciones de visita'
        ordering = ['-visit_date', '-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['route_client', 'visit_date'],
                condition=Q(deleted_at__isnull=True),
                name='route_confirm_active_visit_uniq',
            ),
        ]
        indexes = [
            models.Index(fields=['route_client', 'visit_date'], name='route_confirm_client_date_idx'),
            models.Index(fields=['visit_date'], name='route_confirm_visit_date_idx'),
            models.Index(fields=['status'], name='route_confirm_status_idx'),
            models.Index(fields=['expires_at'], name='route_confirm_expires_idx'),
        ]

    def __str__(self) -> str:
        return f'{self.route_client.client} - {self.visit_date} - {self.display_status()}'

    @staticmethod
    def generate_token() -> str:
        return generate_confirmation_token()

    def reset_token(self) -> None:
        self.token = self.generate_token()

    def is_expired(self, reference_time: datetime | None = None) -> bool:
        if self.expires_at is None:
            return False
        current_time = reference_time or timezone.now()
        return self.expires_at <= current_time

    def display_status(self, reference_time: datetime | None = None) -> str:
        if self.status == self.Status.SENT and self.is_expired(reference_time):
            return 'Expirada'
        return self.status

    def can_resend(self, reference_time: datetime | None = None) -> bool:
        return self.status == self.Status.SENT and self.is_expired(reference_time)
