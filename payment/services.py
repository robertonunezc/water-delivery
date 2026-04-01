from decimal import Decimal
from typing import Optional

from django.contrib.auth.models import User
from django.db import transaction

from clients.services import balance_service
from orders.models import Order, OrderStatus

from .models import Payment


def process_payment_request(
    order: Order,
    data: dict,
    request_user: User,
) -> tuple[dict, int]:
    """Process a payment request payload in either multi or legacy format."""
    payments_data = data.get('payments')
    cantidad_cobrada = data.get('cantidad_cobrada')

    if payments_data and isinstance(payments_data, list):
        return process_multiple_payments(
            order=order,
            payments_data=payments_data,
            cantidad_cobrada=cantidad_cobrada,
            request_user=request_user,
        )

    return process_legacy_payment(
        order=order,
        data=data,
        request_user=request_user,
    )


def process_single_payment(
    order: Order,
    payment_method: str,
    amount: Decimal,
    request_user: User,
    credit_note: Optional[str] = None,
) -> tuple[Optional[Payment], Optional[dict[str, str]]]:
    """Process and persist one payment for an order."""
    client = order.client

    if payment_method == 'balance' and client.balance < amount:
        return None, {
            'error': f'Saldo insuficiente. Disponible: ${client.balance:.2f}, Requerido: ${amount:.2f}'
        }

    if payment_method == 'credit':
        if not client.can_use_credit_for_payment():
            return None, {
                'error': 'Este cliente no puede usar crédito para pagos en este momento.'
            }

        if client.requires_note_for_credit_payment() and (not credit_note or not credit_note.strip()):
            return None, {
                'error': 'Se requiere una nota para pagos con crédito para este cliente.'
            }

        validation_result = client.validate_credit_payment(amount, credit_note)
        if not validation_result['success']:
            return None, {'error': validation_result['error']}

    payment = Payment(
        amount=amount,
        method=payment_method,
        client=client,
        order=order,
        created_by=request_user,
    )

    if payment_method == 'credit' and credit_note:
        payment._credit_note = credit_note.strip()

    # Persist payment first, then apply accounting explicitly.
    with transaction.atomic():
        payment.save(apply_accounting=False)
        if payment.status == 'completed':
            payment.apply_accounting_side_effects()
            payment.save(update_fields=['balance_used', 'credit_used', 'updated_at'], apply_accounting=False)
            payment.link_pending_transaction_references()

    return payment, None


def process_multiple_payments(
    order: Order,
    payments_data: list,
    cantidad_cobrada: Optional[object],
    request_user: User,
) -> tuple[dict, int]:
    """Process multiple payments for one order."""
    if not payments_data:
        return {'error': 'No payments provided'}, 400

    order_total = Decimal(str(order.total_amount))
    total_payment_amount = Decimal('0.00')
    for payment_item in payments_data:
        if 'amount' not in payment_item or 'payment_method' not in payment_item:
            return {'error': 'Cada transaccion de pago debe tener un metodo de pago asignado'}, 400
        total_payment_amount += Decimal(str(payment_item['amount']))

    if total_payment_amount != order_total:
        return {
            'error': (
                f'La suma de los pagos (${total_payment_amount:.2f}) debe ser igual '
                f'al total de la orden (${order_total:.2f})'
            )
        }, 400

    created_payments = []
    for payment_item in payments_data:
        amount = Decimal(str(payment_item['amount']))
        if amount <= 0:
            continue

        payment, error = process_single_payment(
            order=order,
            payment_method=payment_item['payment_method'],
            amount=amount,
            request_user=request_user,
            credit_note=payment_item.get('credit_note'),
        )
        if error:
            return error, 400

        created_payments.append({
            'payment_id': payment.id,
            'amount': str(payment.amount),
            'method': payment.get_method_display(),
            'method_code': payment.method,
        })

    try:
        charged_amount_info = apply_cantidad_cobrada(
            order=order,
            cantidad_cobrada_value=cantidad_cobrada,
            user=request_user,
        )
    except ValueError as exc:
        return {'error': str(exc)}, 400

    order.status = OrderStatus.COMPLETED.value
    order.save()

    response_data = {
        'success': True,
        'payments': created_payments,
        'order_total': str(order.total_amount),
        'payment_count': len(created_payments),
    }
    return _append_cantidad_cobrada_response_fields(response_data, charged_amount_info, order), 200


def process_legacy_payment(
    order: Order,
    data: dict,
    request_user: User,
) -> tuple[dict, int]:
    """Process single-payment payload in legacy format."""
    payment_method = data.get('payment_method')
    amount = data.get('amount')
    cantidad_cobrada = data.get('cantidad_cobrada')
    credit_note = data.get('credit_note')

    if not payment_method:
        return {'error': 'Missing payment_method'}, 400

    order_total = Decimal(str(order.total_amount))
    amount = order_total if not amount else Decimal(str(amount))

    payment, error = process_single_payment(
        order=order,
        payment_method=payment_method,
        amount=amount,
        request_user=request_user,
        credit_note=credit_note,
    )
    if error:
        return error, 400

    try:
        charged_amount_info = apply_cantidad_cobrada(
            order=order,
            cantidad_cobrada_value=cantidad_cobrada,
            user=request_user,
        )
    except ValueError as exc:
        return {'error': str(exc)}, 400

    order.status = OrderStatus.COMPLETED.value
    order.save()

    response_data = {
        'success': True,
        'payment_id': payment.id,
        'amount': str(payment.amount),
        'method': payment.get_method_display(),
        'order_total': str(order.total_amount),
    }
    return _append_cantidad_cobrada_response_fields(response_data, charged_amount_info, order), 200


def apply_cantidad_cobrada(
    order: Order,
    cantidad_cobrada_value: Optional[object],
    user: User,
) -> dict[str, object]:
    """Apply charged amount to order and optionally add excess to client balance."""
    if cantidad_cobrada_value is None:
        return {
            'cantidad_cobrada': None,
            'balance_added': Decimal('0.00'),
        }

    order_total = Decimal(str(order.total_amount))
    cantidad_cobrada = Decimal(str(cantidad_cobrada_value))

    if cantidad_cobrada < order_total:
        raise ValueError(
            f'La cantidad cobrada (${cantidad_cobrada:.2f}) no puede ser menor al total de la orden (${order_total:.2f})'
        )

    order.cantidad_cobrada = cantidad_cobrada
    balance_added = Decimal('0.00')

    if cantidad_cobrada > order_total:
        balance_added = cantidad_cobrada - order_total
        balance_service.add_balance(
            client=order.client,
            amount=balance_added,
            transaction_type='added_in_order',
            user=user,
            reference_order=order,
            notes=(
                f'Saldo agregado en venta - Orden #{order.id}. Diferencia entre cantidad cobrada '
                f'(${cantidad_cobrada:.2f}) y total de orden (${order_total:.2f})'
            ),
        )

    return {
        'cantidad_cobrada': cantidad_cobrada,
        'balance_added': balance_added,
    }


def _append_cantidad_cobrada_response_fields(
    response_data: dict,
    charged_amount_info: dict[str, object],
    order: Order,
) -> dict:
    """Add optional charged-amount response fields used by frontend messages."""
    if charged_amount_info['cantidad_cobrada'] is not None and charged_amount_info['balance_added'] > 0:
        response_data['balance_added'] = str(charged_amount_info['balance_added'])
        response_data['cantidad_cobrada'] = str(charged_amount_info['cantidad_cobrada'])
        response_data['new_client_balance'] = str(order.client.balance)
    return response_data