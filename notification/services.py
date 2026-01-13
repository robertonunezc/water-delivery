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
                to="robert@puntoreica.com",
                from_="Mailgun Sandbox <postmaster@sandbox40fe3482053c4675b353e6270f32bbe5.mailgun.org>",
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