from django.shortcuts import get_object_or_404
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from notification.models import Notification
from notification.services import send_notification


def send_notification_view(request, notification_id: int) -> JsonResponse:
    """
    Envía una notificación específica por su ID.
    
    Args:
        request: HttpRequest object
        notification_id: ID de la notificación a enviar
        
    Returns:
        JsonResponse con el estado del envío
    """
    notification = get_object_or_404(Notification, id=notification_id)
    
    if notification.status == 'sent':
        return JsonResponse(
            {
                'success': False,
                'message': 'La notificación ya fue enviada',
                'notification_id': notification_id,
                'status': notification.status
            },
            status=400
        )
    
    send_notification(notification)
    
    return JsonResponse(
        {
            'success': notification.status == 'sent',
            'message': 'Notificación enviada con éxito' if notification.status == 'sent' else 'Error al enviar la notificación',
            'notification_id': notification_id,
            'status': notification.status,
            'sent_at': notification.sent_at.isoformat() if notification.sent_at else None
        },
        status=200 if notification.status == 'sent' else 500
    )
