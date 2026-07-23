from decimal import Decimal
from typing import TYPE_CHECKING, Optional
from dataclasses import dataclass, asdict
from django.contrib.auth.models import User
from django.db import transaction

from clients.services import balance_service
from orders.models import Order, OrderStatus

from .models import Payment

if TYPE_CHECKING:
    from clients.models import Client


VALID_SETTLEMENT_METHODS = {
    'credit_card',
    'debit_card',
    'cash',
    'balance',
    'paypal',
    'bank_transfer',
}


class ClientOrderPaymentError(ValueError):
    """Raised when a client-level order payment cannot be processed."""


@dataclass
class PaymentRequestData:
    payments_data: Optional[list[dict]] = None
    payment_method: Optional[str] = None
    cantidad_cobrada: Optional[Decimal] = None
    order_type: Optional[str] = None
    amount: Optional[Decimal] = None
    credit_note: Optional[str] = None
    notes: Optional[str] = None


def get_unpaid_amount(order: Order) -> Decimal:
    """Return the remaining unpaid amount for an order."""
    return max(
        Decimal(str(order.total_amount)) - Decimal(str(order.total_paid)),
        Decimal('0.00'),
    )


def get_selected_unpaid_orders(client: "Client", order_ids: list[int]) -> list[Order]:
    """Return selected unpaid orders for a client, preserving submitted order."""
    if not order_ids:
        raise ClientOrderPaymentError('Selecciona al menos un pedido para pagar.')

    deduped_ids = list(dict.fromkeys(order_ids))
    orders_by_id = {
        order.id: order
        for order in Order.objects.filter(pk__in=deduped_ids)
        .select_related('client')
        .prefetch_related('payments')
    }
    selected_orders = []
    for order_id in deduped_ids:
        order = orders_by_id.get(order_id)
        if order is None:
            raise ClientOrderPaymentError(f'Pedido #{order_id} no encontrado.')
        selected_orders.append(order)

    _validate_selected_orders(client=client, orders=selected_orders)
    return selected_orders


def _validate_selected_orders(client: "Client", orders: list[Order]) -> None:
    if not orders:
        raise ClientOrderPaymentError('Selecciona al menos un pedido para pagar.')

    for order in orders:
        if order.client_id != client.id:
            raise ClientOrderPaymentError(f'El pedido #{order.id} no pertenece al cliente.')
        if order.status == OrderStatus.CANCELLED.value:
            raise ClientOrderPaymentError(f'El pedido #{order.id} está cancelado.')
        if get_unpaid_amount(order) <= 0:
            raise ClientOrderPaymentError(f'El pedido #{order.id} ya está pagado.')


@transaction.atomic
def pay_client_orders(
    client: "Client",
    orders: list[Order],
    payment_method: str,
    amount: Decimal,
    request_user: User,
) -> dict[str, object]:
    """Pay selected unpaid client orders and add overpayment to balance."""
    selected_orders = get_selected_unpaid_orders(
        client=client,
        order_ids=[order.id for order in orders],
    )
    amount = Decimal(str(amount))
    selected_total = sum(
        (get_unpaid_amount(order) for order in selected_orders),
        Decimal('0.00'),
    )
    if amount < selected_total:
        raise ClientOrderPaymentError(
            f'El monto ${amount:.2f} es menor al total seleccionado ${selected_total:.2f}.'
        )

    created_payments = []
    for order in selected_orders:
        order_amount = get_unpaid_amount(order)
        if order_amount <= 0:
            raise ClientOrderPaymentError(f'El pedido #{order.id} ya está pagado.')

        pending_credit = order.payments.select_for_update().filter(
            method='pending_credit',
            status='pending',
        ).first()
        if pending_credit:
            payment, error = settle_credit_order_payment(
                order=order,
                payment_method=payment_method,
                amount=order_amount,
                request_user=request_user,
            )
        else:
            payment, error = process_single_payment(
                order=order,
                payment_method=payment_method,
                amount=order_amount,
                request_user=request_user,
            )
        if error:
            raise ClientOrderPaymentError(error['error'])
        created_payments.append(payment)

    balance_added = amount - selected_total
    if balance_added > 0:
        balance_service.add_balance(
            client=client,
            amount=balance_added,
            transaction_type='added_in_order',
            user=request_user,
            reference_order=selected_orders[-1],
            notes=(
                f'Saldo agregado por excedente en pago de pedidos '
                f'{", ".join(f"#{order.id}" for order in selected_orders)}. '
                f'Excedente: ${balance_added:.2f}.'
            ),
        )

    return {
        'selected_total': selected_total,
        'amount_received': amount,
        'balance_added': balance_added,
        'payments': created_payments,
        'orders': selected_orders,
    }


def process_payment_request(
    order: Order,
    data: PaymentRequestData,
    request_user: User,
) -> tuple[dict, int]:
    """Process a payment request payload in either multi or legacy format."""
    if data.cantidad_cobrada is not None and Decimal(str(data.cantidad_cobrada)) < order.total_amount:
        raise ValueError(f'Cantidad a cobrar menor que el total de la orden: ${data.cantidad_cobrada} < ${order.total_amount}')
    if data.notes is not None:
        order.notes = data.notes.strip() or None
        order.save(update_fields=['notes', 'updated_at'])
    requested_type = data.order_type
    _apply_order_type(order=order, requested_type=requested_type)

    if order.type == 'credito':
        return _process_credit_order_flow(order=order, data=data, request_user=request_user)

    payments_data = data.payments_data
    cantidad_cobrada = data.cantidad_cobrada

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
    if payment_method not in VALID_SETTLEMENT_METHODS:
        return None, {
            'error': 'Método de pago inválido para este flujo.'
        }

    client = order.client

    if payment_method == 'balance' and client.balance < amount:
        return None, {
            'error': f'Saldo insuficiente. Disponible: ${client.balance:.2f}, Requerido: ${amount:.2f}'
        }

    payment = Payment(
        amount=amount,
        method=payment_method,
        client=client,
        order=order,
        created_by=request_user,
    )

    # Persist payment first, then apply accounting explicitly.
    with transaction.atomic():
        payment.save(apply_accounting=False)
        if payment.status == 'completed':
            payment.apply_accounting_side_effects()
            payment.save(update_fields=['balance_used', 'updated_at'], apply_accounting=False)
            payment.link_pending_transaction_references()

    return payment, None


@transaction.atomic
def settle_credit_order_payment(
    order: Order,
    payment_method: str,
    amount: Decimal,
    request_user: User,
) -> tuple[Optional[Payment], Optional[dict[str, str]]]:
    """Record a credit-order payment and reduce the client's debt atomically."""
    pending_credit = order.payments.select_for_update().filter(
        method='pending_credit',
        status='pending',
    ).first()
    if pending_credit is None:
        return None, {'error': 'La orden no tiene crédito pendiente por liquidar.'}

    reconciled_payment = _reconcile_unapplied_credit_payment(
        order=order,
        pending_credit=pending_credit,
        request_user=request_user,
    )
    if reconciled_payment:
        return reconciled_payment, None

    amount_due = Decimal(str(pending_credit.amount))
    if amount != amount_due:
        return None, {
            'error': (
                f'El pago debe cubrir el saldo pendiente de ${amount_due:.2f}.'
            ),
        }

    payment, error = process_single_payment(
        order=order,
        payment_method=payment_method,
        amount=amount,
        request_user=request_user,
    )
    if error:
        return None, error

    paid_amount = balance_service.pay_debt(
        client=order.client,
        amount=amount,
        transaction_type='payment',
        user=request_user,
        reference_order=order,
        reference_payment=payment,
        notes=f'Liquidación de orden a crédito #{order.id}',
    )
    if paid_amount != amount:
        raise ValueError('No se pudo aplicar el pago completo a la deuda del cliente.')

    _complete_pending_credit(pending_credit)
    return payment, None


def _reconcile_unapplied_credit_payment(
    order: Order,
    pending_credit: Payment,
    request_user: User,
) -> Optional[Payment]:
    """Apply a previously recorded payment that did not reduce credit debt."""
    accounted_payment_ids = order.client.credit_transactions.filter(
        reference_order=order,
        transaction_type='payment',
        reference_payment__isnull=False,
    ).values('reference_payment_id')
    payment = order.payments.filter(
        status='completed',
        date__gt=pending_credit.date,
    ).exclude(
        method='pending_credit',
    ).exclude(
        pk__in=accounted_payment_ids,
    ).order_by('date').first()
    if payment is None:
        return None

    amount_due = Decimal(str(pending_credit.amount))
    if payment.amount != amount_due:
        raise ValueError(
            'Existe un pago previo sin aplicar cuyo monto no coincide con el saldo '
            'pendiente. Se requiere revisión manual antes de registrar otro pago.'
        )

    paid_amount = balance_service.pay_debt(
        client=order.client,
        amount=payment.amount,
        transaction_type='payment',
        user=request_user,
        reference_order=order,
        reference_payment=payment,
        notes=f'Reconciliación de pago de orden a crédito #{order.id}',
    )
    if paid_amount != payment.amount:
        raise ValueError('No se pudo reconciliar el pago con la deuda del cliente.')

    _complete_pending_credit(pending_credit)
    return payment


def _complete_pending_credit(pending_credit: Payment) -> None:
    pending_credit.status = 'completed'
    pending_credit.save(
        update_fields=['status', 'updated_at'],
        apply_accounting=False,
    )


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
    data: PaymentRequestData,
    request_user: User,
) -> tuple[dict, int]:
    """Process single-payment payload in legacy format."""
    payment_method = data.payment_method
    if not payment_method and data.payments_data and isinstance(data.payments_data, list):
        payment_method = data.payments_data[0]
        
    amount = data.amount
    cantidad_cobrada = data.cantidad_cobrada
    credit_note = data.credit_note

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


def _apply_order_type(order: Order, requested_type: Optional[str]) -> None:
    """Persist incoming order type when it changes in the checkout UI."""
    if requested_type not in {'contado', 'credito'}:
        return

    if order.type != requested_type:
        order.type = requested_type
        order.save(update_fields=['type', 'updated_at'])


def _process_credit_order_flow(
    order: Order,
    data: PaymentRequestData,
    request_user: User,
) -> tuple[dict, int]:
    """Process credit-order lifecycle: debt registration and later settlement."""
    pending_credit_payment = order.payments.filter(method='pending_credit', status='pending').first()

    payments_data = data.payments_data
    if pending_credit_payment and payments_data:
        return _settle_pending_credit_order(
            order=order,
            payments_data=payments_data,
            request_user=request_user,
            pending_credit_payment=pending_credit_payment,
        )
    
    return _register_credit_order_debt(order=order, request_user=request_user)


def _register_credit_order_debt(order: Order, request_user: User) -> tuple[dict, int]:
    """Apply prepaid balance first, then register the remaining order debt."""
    existing_credit_payment = order.payments.filter(method='pending_credit').first()
    if existing_credit_payment:
        return {
            'success': True,
            'order_pending_credit': existing_credit_payment.status == 'pending',
            'message': 'La orden a credito ya tiene un registro pendiente de liquidacion.',
            'order_status': order.status,
        }, 200

    existing_purchase = order.client.credit_transactions.filter(
        reference_order=order,
        transaction_type='purchase',
    ).first()

    order_total = Decimal(str(order.total_amount))
    client_balance = Decimal(str(order.client.balance))
    balance_amount = min(client_balance, order_total)
    credit_amount = order_total - balance_amount

    try:
        with transaction.atomic():
            if balance_amount > 0:
                payment, error = process_single_payment(
                    order=order,
                    payment_method='balance',
                    amount=balance_amount,
                    request_user=request_user,
                )
                if error:
                    raise ValueError(error['error'])

            pending_payment = None
            if credit_amount > 0:
                pending_payment = Payment(
                    amount=credit_amount,
                    method='pending_credit',
                    client=order.client,
                    order=order,
                    status='pending',
                    created_by=request_user,
                )
                pending_payment.save(apply_accounting=False)

            if credit_amount > 0 and not existing_purchase:
                balance_service.add_debt(
                    client=order.client,
                    amount=credit_amount,
                    transaction_type='purchase',
                    user=request_user,
                    reference_order=order,
                    reference_payment=pending_payment,
                    notes=f'Pedido #{order.id} registrado a crédito y pendiente de pago',
                )

            if order.status != OrderStatus.COMPLETED.value:
                order.status = OrderStatus.COMPLETED.value
                order.save(update_fields=['status', 'updated_at'])
    except ValueError as exc:
        return {'error': str(exc)}, 400

    if credit_amount == 0:
        return {
            'success': True,
            'order_pending_credit': False,
            'message': 'Orden pagada completamente con saldo disponible.',
            'order_status': order.status,
        }, 200

    return {
        'success': True,
        'order_pending_credit': True,
        'message': 'Orden a crédito registrada. Queda pendiente de pago.',
        'order_status': order.status,
    }, 200


def _settle_pending_credit_order(
    order: Order,
    payments_data: list,
    request_user: User,
    pending_credit_payment: Payment,
) -> tuple[dict, int]:
    """Settle an existing pending credit order and close associated debt."""
    if not payments_data:
        return {'error': 'No payments provided'}, 400

    amount_due = Decimal(str(pending_credit_payment.amount))
    total_payment_amount = Decimal('0.00')
    for payment_item in payments_data:
        if 'amount' not in payment_item or 'payment_method' not in payment_item:
            return {'error': 'Cada transaccion de pago debe tener un metodo de pago asignado'}, 400
        total_payment_amount += Decimal(str(payment_item['amount']))

    if total_payment_amount != amount_due:
        return {
            'error': (
                f'La suma de los pagos (${total_payment_amount:.2f}) debe ser igual '
                f'al saldo pendiente (${amount_due:.2f})'
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
        )
        if error:
            return error, 400

        paid_amount = balance_service.pay_debt(
            client=order.client,
            amount=amount,
            transaction_type='payment',
            user=request_user,
            reference_order=order,
            reference_payment=payment,
            notes=f'Liquidación de orden a crédito #{order.id}',
        )
        if paid_amount <= 0:
            return {
                'error': 'No se pudo aplicar el pago a la deuda del cliente.'
            }, 400

        created_payments.append({
            'payment_id': payment.id,
            'amount': str(payment.amount),
            'method': payment.get_method_display(),
            'method_code': payment.method,
        })

    with transaction.atomic():
        pending_credit_payment.status = 'completed'
        pending_credit_payment.save(update_fields=['status', 'updated_at'], apply_accounting=False)

        order.status = OrderStatus.COMPLETED.value
        order.save(update_fields=['status', 'updated_at'])

    return {
        'success': True,
        'payments': created_payments,
        'order_total': str(order.total_amount),
        'payment_count': len(created_payments),
        'credit_order_settled': True,
    }, 200
