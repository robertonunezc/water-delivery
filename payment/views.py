from django.shortcuts import get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.db import transaction
import json

from . import services as payment_services
from orders.models import Order


def process_single_payment(order, payment_method, amount, request_user, credit_note=None):
    """
    Process a single payment for an order.
    Returns (payment, error_dict) tuple. If error_dict is not None, the payment failed.
    """
    return payment_services.process_single_payment(
        order=order,
        payment_method=payment_method,
        amount=amount,
        request_user=request_user,
        credit_note=credit_note,
    )


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
    cantidad_cobrada = data.get('cantidad_cobrada')
    
    if not order_id:
        return JsonResponse({'error': 'Missing order_id'}, status=400)

    try:
        order = get_object_or_404(Order, pk=order_id)
        response_data, status_code = payment_services.process_payment_request(
            order=order,
            data=data,
            request_user=request.user,
        )
        return JsonResponse(response_data, status=status_code)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


def process_multiple_payments(request, order, payments_data, cantidad_cobrada):
    """
    Process multiple payments for an order (e.g., balance + another method).
    Payments are processed in order - balance should come first.
    """
    response_data, status_code = payment_services.process_multiple_payments(
        order=order,
        payments_data=payments_data,
        cantidad_cobrada=cantidad_cobrada,
        request_user=request.user,
    )
    return JsonResponse(response_data, status=status_code)


def process_legacy_payment(request, order, data):
    """
    Process a single payment in the legacy format (backward compatible).
    """
    response_data, status_code = payment_services.process_legacy_payment(
        order=order,
        data=data,
        request_user=request.user,
    )
    return JsonResponse(response_data, status=status_code)
