from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.db import transaction
from decimal import Decimal
import json

from .models import Payment
from orders.models import OrderStatus, Order


def process_single_payment(order, payment_method, amount, request_user, credit_note=None):
    """
    Process a single payment for an order.
    Returns (payment, error_dict) tuple. If error_dict is not None, the payment failed.
    """
    client = order.client
    
    # Validate balance payment
    if payment_method == 'balance':
        if client.balance < amount:
            return None, {
                'error': f'Saldo insuficiente. Disponible: ${client.balance:.2f}, Requerido: ${amount:.2f}'
            }
    
    # Validate credit payment restrictions
    if payment_method == 'credit':
        # Check if client can use credit
        if not client.can_use_credit_for_payment():
            return None, {
                'error': 'Este cliente no puede usar crédito para pagos en este momento.'
            }
        
        # Check if credit note is required
        if client.requires_note_for_credit_payment():
            if not credit_note or not credit_note.strip():
                return None, {
                    'error': 'Se requiere una nota para pagos con crédito para este cliente.'
                }
        
        # Validate client has sufficient credit
        validation_result = client.validate_credit_payment(amount, credit_note)
        if not validation_result['success']:
            return None, {'error': validation_result['error']}
    
    # Create payment
    payment = Payment(
        amount=amount,
        method=payment_method,
        client=client,
        order=order,
        created_by=request_user
    )
    
    # For credit payments, set the credit note before saving
    if payment_method == 'credit' and credit_note:
        payment._credit_note = credit_note.strip()
    
    # Save the payment (this will trigger the custom save logic for balance/credit deduction)
    payment.save()
    
    return payment, None


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
        
        # Determine if this is a multi-payment request or single payment
        payments_data = data.get('payments')
        
        if payments_data and isinstance(payments_data, list):
            # New format: array of payments
            return process_multiple_payments(request, order, payments_data, cantidad_cobrada)
        else:
            # Old format: single payment (backward compatible)
            return process_legacy_payment(request, order, data)
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


def process_multiple_payments(request, order, payments_data, cantidad_cobrada):
    """
    Process multiple payments for an order (e.g., balance + another method).
    Payments are processed in order - balance should come first.
    """
    if not payments_data:
        return JsonResponse({'error': 'No payments provided'}, status=400)
    
    order_total = Decimal(str(order.total_amount))
    
    # Validate total of all payments equals order total
    total_payment_amount = Decimal('0.00')
    for p in payments_data:
        if 'amount' not in p or 'payment_method' not in p:
            return JsonResponse({'error': 'Each payment must have amount and payment_method'}, status=400)
        total_payment_amount += Decimal(str(p['amount']))
    
    if total_payment_amount != order_total:
        return JsonResponse({
            'error': f'La suma de los pagos (${total_payment_amount:.2f}) debe ser igual al total de la orden (${order_total:.2f})'
        }, status=400)
    
    # Process each payment
    created_payments = []
    for payment_data in payments_data:
        amount = Decimal(str(payment_data['amount']))
        payment_method = payment_data['payment_method']
        credit_note = payment_data.get('credit_note')
        
        # Skip payments with zero amount
        if amount <= 0:
            continue
        
        payment, error = process_single_payment(
            order=order,
            payment_method=payment_method,
            amount=amount,
            request_user=request.user,
            credit_note=credit_note
        )
        
        if error:
            return JsonResponse(error, status=400)
        
        created_payments.append({
            'payment_id': payment.id,
            'amount': str(payment.amount),
            'method': payment.get_method_display(),
            'method_code': payment.method
        })
    
    # Handle cantidad_cobrada (amount actually charged to customer)
    if cantidad_cobrada is not None:
        cantidad_cobrada = Decimal(str(cantidad_cobrada))
        
        if cantidad_cobrada < order_total:
            return JsonResponse({
                'error': f'La cantidad cobrada (${cantidad_cobrada:.2f}) no puede ser menor al total de la orden (${order_total:.2f})'
            }, status=400)
        
        order.cantidad_cobrada = cantidad_cobrada
        
        # If cantidad_cobrada is greater than order total, add difference to client balance
        if cantidad_cobrada > order_total:
            from clients.services import balance_service
            excess_amount = cantidad_cobrada - order_total
            balance_service.add_balance(
                client=order.client,
                amount=excess_amount,
                transaction_type='added_in_order',
                user=request.user,
                reference_order=order,
                notes=f'Saldo agregado en venta - Orden #{order.id}. Diferencia entre cantidad cobrada (${cantidad_cobrada:.2f}) y total de orden (${order_total:.2f})'
            )

    # Update order status
    order.status = OrderStatus.COMPLETED.value
    order.save()

    # Build response
    response_data = {
        'success': True,
        'payments': created_payments,
        'order_total': str(order.total_amount),
        'payment_count': len(created_payments)
    }
    
    # Include balance addition info if applicable
    if cantidad_cobrada is not None and cantidad_cobrada > order_total:
        excess_amount = cantidad_cobrada - order_total
        response_data['balance_added'] = str(excess_amount)
        response_data['cantidad_cobrada'] = str(cantidad_cobrada)
        response_data['new_client_balance'] = str(order.client.balance)
    
    return JsonResponse(response_data)


def process_legacy_payment(request, order, data):
    """
    Process a single payment in the legacy format (backward compatible).
    """
    payment_method = data.get('payment_method')
    amount = data.get('amount')
    cantidad_cobrada = data.get('cantidad_cobrada')
    credit_note = data.get('credit_note')

    if not payment_method:
        return JsonResponse({'error': 'Missing payment_method'}, status=400)
    
    order_total = Decimal(str(order.total_amount))
    
    # Use order total if amount not provided
    if not amount:
        amount = order_total
    else:
        amount = Decimal(str(amount))
    
    # Process the payment
    payment, error = process_single_payment(
        order=order,
        payment_method=payment_method,
        amount=amount,
        request_user=request.user,
        credit_note=credit_note
    )
    
    if error:
        return JsonResponse(error, status=400)
    
    # Handle cantidad_cobrada
    if cantidad_cobrada is not None:
        cantidad_cobrada = Decimal(str(cantidad_cobrada))
        
        if cantidad_cobrada < order_total:
            return JsonResponse({
                'error': f'La cantidad cobrada (${cantidad_cobrada:.2f}) no puede ser menor al total de la orden (${order_total:.2f})'
            }, status=400)
        
        order.cantidad_cobrada = cantidad_cobrada
        
        # If cantidad_cobrada is greater than order total, add difference to client balance
        if cantidad_cobrada > order_total:
            from clients.services import balance_service
            excess_amount = cantidad_cobrada - order_total
            balance_service.add_balance(
                client=order.client,
                amount=excess_amount,
                transaction_type='added_in_order',
                user=request.user,
                reference_order=order,
                notes=f'Saldo agregado en venta - Orden #{order.id}. Diferencia entre cantidad cobrada (${cantidad_cobrada:.2f}) y total de orden (${order_total:.2f})'
            )

    # Update order status
    order.status = OrderStatus.COMPLETED.value
    order.save()

    response_data = {
        'success': True,
        'payment_id': payment.id,
        'amount': str(payment.amount),
        'method': payment.get_method_display(),
        'order_total': str(order.total_amount)
    }
    
    # Include balance addition info if applicable
    if cantidad_cobrada is not None and cantidad_cobrada > order_total:
        excess_amount = cantidad_cobrada - order_total
        response_data['balance_added'] = str(excess_amount)
        response_data['cantidad_cobrada'] = str(cantidad_cobrada)
        response_data['new_client_balance'] = str(order.client.balance)
    
    return JsonResponse(response_data)
