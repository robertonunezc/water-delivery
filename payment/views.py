from django.shortcuts import get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.db import transaction
import json

from payment import services
from payment.services import PaymentRequestData
from orders.models import Order


@login_required
@require_http_methods(["POST"])
@transaction.atomic
def create_payment(request):
    """
    Create payment(s) for an order.
    
    Supports two formats:
    1. Single payment (backward compatible):
       { order_id, payment_method, amount, credit_note?, cantidad_cobrada? }
    
    2. Multiple payments (new format - balance first):
       { order_id, payments: [{amount, payment_method, credit_note?}, ...], cantidad_cobrada? }
    """
    try:
        data = json.loads(request.body.decode('utf-8') or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    order_id = data.get('order_id')
    if not order_id:
        return JsonResponse({'error': 'Missing order_id'}, status=400)
    try:
        order = get_object_or_404(Order, pk=order_id)
        request_data = PaymentRequestData(
            payments_data=data.get('payments'),
            payment_method=data.get('payment_method'),
            cantidad_cobrada=data.get('cantidad_cobrada'),
            amount=data.get('amount'),
            credit_note=data.get('credit_note'),
            order_type=data.get('order_type'),
        )
        response_data, status_code = services.process_payment_request(
            order=order,
            data=request_data,
            request_user=request.user,
        )
        return JsonResponse(response_data, status=status_code)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)
