from datetime import datetime
from core import models
from notification.channels.email import SendEmail
from notification.models import Notification
from django.utils import timezone

def create_notification(client, title, message, channel, type):
    """
    Crea una nueva notificación para un cliente específico.
    """

    notification = Notification.objects.create(
        client=client,
        title=title,
        message=message,
        channel=channel,
        type=type,
        status='pending'
    )
    return notification

def send_notification(notification):
    """
    Envia una notificación a través del canal especificado.
    Actualiza el estado de la notificación según el resultado del envío.
    """
    try:
        # Lógica simulada de envío
        if notification.channel == 'email':
            email_client = SendEmail(
                #to=notification.client.email,
                to="rcorralesn@gmail.com",
                from_="WaterDelivery<soporte@puntoreica.com>",
                subject=notification.title,
                body=notification.message
            )
            email_client.send_email()
            print(f"Enviando email a {notification.client}: {notification.message}")
        elif notification.channel == 'sms':
            print(f"Enviando SMS a {notification.client.phone}: {notification.message}")
        elif notification.channel == 'whatsapp':
            print(f"Enviando WhatsApp a {notification.client.whatsapp_number}: {notification.message}")
        else:
            raise ValueError("Canal de notificación no soportado")

        # Si el envío es exitoso
        notification.status = 'sent'
        notification.sent_at = timezone.now()
        notification.save()
        print("Notificación enviada con éxito.")
    except Exception as e:
        # Si hay un error en el envío
        notification.status = 'failed'
        notification.save()
        print(f"Error al enviar la notificación: {e}")

def notify_clients_to_pay():
    """
    Crea y envia todas las notificaciones a los clientes dentro de un rango de fechas.
    Notas:
        - start_date y end_date deben ser objetos datetime.
        - Un cliente debe tener configuraciones de notificación para recibir notificaciones.
        - Un cliente puede tener solo 3 notificaciones enviadas.
        - Una vez enviadas las 3 notificaciones se debe cancelar el servicio.(esto se maneja en otro lugar)
        - Antes de enviar una notificación se debe verificar que no se haya enviado previamente.
        - Las notificaciones se envían según la configuración del cliente.
    """
    # I need to get all clients with less than 3 notifications sent, that are active and have notification settings
    from clients.models import Client
    # Hay alguna condicion para filtrar los clientes que necesitan envio notificacion?
    
    """
    
 1. get_clients_needing_first_reminder(check_date)
   - Filter active clients requiring(requires_billing) billing or (can_pay_with_credit and max_payment_days > 0)
   - Exclude clients notified in last 24 hours
   - Calculate trigger date based on ClientNotificationSetting
   - Return list of dicts with client, settings, reference_date
 2. get_clients_needing_second_reminder(check_date)
   - Similar to above but requires last_first_reminder_sent_at not null
   - Supports last_notification_sent condition
 3. get_clients_needing_cancellation(check_date)
   - Requires last_second_reminder_sent_at not null
 4. batch_create_notifications(notification_data_list, type)
   - Create multiple Notification records in single transaction
   - Use message templates for each type
   - Calculate amounts from client.current_debt
 5. batch_send_notifications(notifications, update_field)
   - Send notifications via existing send_notification()
   - Update client tracking timestamp on success
   - Return stats: {sent: N, failed: M}
 6. process_daily_notifications(check_date)
   - Main orchestration function
   - Process all 3 notification types sequentially
   - Return comprehensive stats
    """
