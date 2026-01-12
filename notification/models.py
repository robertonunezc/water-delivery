from django.db import models

from core.models import TimeStampedModel

# Create your models here.
NOTIFICATIONS_TYPES = [
    ('reminder', 'Recordatorio'),
    ('billing_soft_alert', '1era Notificación'),
    ('billing_hard_alert', '2da Notificación'),
    ('service_cancellation', 'Cancelación de Servicio'),
]
NOTIFICATIONS_CHANNELS = [
    ('email', 'Email'),
    ('sms', 'SMS'),
    ('whatsapp', 'WhatsApp'),
]
class Notification(TimeStampedModel):
    title = models.CharField(max_length=255)
    message = models.TextField()
    client = models.ForeignKey('clients.Client', on_delete=models.CASCADE, related_name='notifications')
    type = models.CharField(choices=NOTIFICATIONS_TYPES, max_length=50)
    channel = models.CharField(choices=NOTIFICATIONS_CHANNELS, max_length=50)
    sent_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    status = models.CharField(choices=[('pending', 'Pendiente'), ('sent', 'Enviado'), ('failed', 'Fallido')],default='pending', max_length=20)
    def __str__(self):
        return self.title

    class Meta:
        verbose_name = "Notificación"
        verbose_name_plural = "Notificaciones"

BILLING_NOTIFICATION_CONDITION = [
    ('billing_sent', 'Envio de Facturación'),
    ('credit_days', 'Venceimiento de Días de Crédito'),
    ('last_notification_sent', 'Última Notificación Enviada'),
    ]
BILLING_NOTIFICATION_MOMENTS = [
    ('before', 'Antes'),
    ('after', 'Después'),
]
class ClientNotificationSetting(TimeStampedModel):
    client = models.OneToOneField('clients.Client', on_delete=models.CASCADE, related_name='notification_setting')
    first_reminder_days = models.PositiveIntegerField(default=10, help_text="Días antes del vencimiento para el primer recordatorio")
    first_condition = models.CharField(choices=BILLING_NOTIFICATION_CONDITION,default='credit_days', max_length=50, help_text="Condición para enviar notificaciones de facturación")
    first_moment = models.CharField(choices=BILLING_NOTIFICATION_MOMENTS, max_length=50,default='after', help_text="Momento para enviar notificaciones de facturación")
    second_reminder_days = models.PositiveIntegerField(default=5, help_text="Días antes del vencimiento para la segunda notificación")
    second_condition = models.CharField(choices=BILLING_NOTIFICATION_CONDITION,default='credit_days', max_length=50, help_text="Condición para enviar notificaciones de facturación")
    second_moment = models.CharField(choices=BILLING_NOTIFICATION_MOMENTS, max_length=50,default='after', help_text="Momento para enviar notificaciones de facturación")
    cancellation_days = models.PositiveIntegerField(default=0, help_text="Días después del vencimiento para la cancelación del servicio")
    cancellation_condition = models.CharField(choices=BILLING_NOTIFICATION_CONDITION,default='credit_days', max_length=50, help_text="Condición para enviar notificaciones de facturación")
    cancellation_moment = models.CharField(choices=BILLING_NOTIFICATION_MOMENTS, max_length=50,default='after', help_text="Momento para enviar notificaciones de facturación")
    def __str__(self):
        return f"Configuracion de notificationes {self.client.name}"

    class Meta:
        verbose_name = "Configuración de Notificación de cliente"
        verbose_name_plural = "Configuraciones de Notificaciones de cliente"