from decimal import Decimal
from typing import Optional

from django.contrib.auth.models import User

from clients.services import balance_service
from orders.models import Order

from .models import Payment


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

    # Payment.save handles balance/credit accounting for completed payments.
    payment.save()
    return payment, None


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