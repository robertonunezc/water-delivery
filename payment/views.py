from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.db import transaction
import json

from .models import Payment
from orders.models import OrderStatus, Order

@login_required
@require_http_methods(["POST"])
@transaction.atomic
def create_payment(request):
    try:
        data = json.loads(request.body.decode('utf-8') or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    order_id = data.get('order_id')
    payment_method = data.get('payment_method')
    amount = data.get('amount')

    if not order_id or not payment_method:
        return JsonResponse({'error': 'Missing required fields'}, status=400)

    try:
        order = get_object_or_404(Order, pk=order_id)
        
        # Use order total if amount not provided
        if not amount:
            amount = order.total_amount
        
        # Create payment
        payment = Payment.objects.create(
            amount=amount,
            method=payment_method,
            client=order.client,
            order=order
        )
        
        order.status = OrderStatus.COMPLETED 
        order.save()
        
        return JsonResponse({
            'success': True,
            'payment_id': payment.id,
            'amount': str(payment.amount),
            'method': payment.get_method_display()
        })
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)
