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
    cantidad_cobrada = data.get('cantidad_cobrada')  # New field
    credit_note = data.get('credit_note')  # Credit note for restricted clients

    if not order_id or not payment_method:
        return JsonResponse({'error': 'Missing required fields'}, status=400)

    try:
        order = get_object_or_404(Order, pk=order_id)
        
        # Use order total if amount not provided
        if not amount:
            amount = order.total_amount
        
        # Validate credit payment restrictions
        if payment_method == 'credit':
            # Check if client can use credit
            if not order.client.can_use_credit_for_payment():
                return JsonResponse({
                    'error': 'Este cliente no puede usar crédito para pagos en este momento.'
                }, status=400)
            
            # Check if credit note is required
            if order.client.requires_note_for_credit_payment():
                if not credit_note or not credit_note.strip():
                    return JsonResponse({
                        'error': 'Se requiere una nota para pagos con crédito para este cliente.'
                    }, status=400)
            
            # Validate client has sufficient credit
            validation_result = order.client.validate_credit_payment(amount, credit_note)
            if not validation_result['success']:
                return JsonResponse({
                    'error': validation_result['error']
                }, status=400)
        
        # Validate cantidad_cobrada
        if cantidad_cobrada is not None:
            from decimal import Decimal
            cantidad_cobrada = Decimal(str(cantidad_cobrada))
            order_total = Decimal(str(order.total_amount))
            
            if cantidad_cobrada < order_total:
                return JsonResponse({
                    'error': f'La cantidad cobrada (${cantidad_cobrada:.2f}) no puede ser menor al total de la orden (${order_total:.2f})'
                }, status=400)
            
            # Update order with cantidad_cobrada
            order.cantidad_cobrada = cantidad_cobrada
            
            # If cantidad_cobrada is greater than order total, add difference to client balance
            if cantidad_cobrada > order_total:
                excess_amount = cantidad_cobrada - order_total
                
                # Add balance to client using BalanceTransaction
                order.client.add_balance(
                    amount=excess_amount,
                    transaction_type='added_in_order',
                    user=request.user,
                    reference_order=order,
                    notes=f'Saldo agregado en venta - Orden #{order.id}. Diferencia entre cantidad cobrada (${cantidad_cobrada:.2f}) y total de orden (${order_total:.2f})'
                )
        
        # Create payment for the order amount (not the cantidad_cobrada)
        payment = Payment(
            amount=order.total_amount,  # Payment is always for the order total
            method=payment_method,
            client=order.client,
            order=order,
            created_by=request.user
        )
        
        # For credit payments, set the credit note before saving
        if payment_method == 'credit' and credit_note:
            payment._credit_note = credit_note.strip()
        
        # Save the payment (this will trigger the custom save logic)
        payment.save()
        
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
        if cantidad_cobrada is not None and cantidad_cobrada > order.total_amount:
            excess_amount = cantidad_cobrada - order.total_amount
            response_data['balance_added'] = str(excess_amount)
            response_data['cantidad_cobrada'] = str(cantidad_cobrada)
            response_data['new_client_balance'] = str(order.client.balance)
        
        return JsonResponse(response_data)
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)
