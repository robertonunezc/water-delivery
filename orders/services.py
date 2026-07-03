from datetime import date
from decimal import Decimal
from django.db import transaction
from django.db.models import ProtectedError
from django.db.models import Count, Sum
from clients.models import Client
from core import models
from orders.models import Order, OrderProduct, OrderStatus
from product.models import ProductClientPrice
from dataclasses import dataclass
from typing import List, Optional, Dict
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


def get_sales_snapshot(start_date: date, end_date: date) -> dict[str, object]:
    """Return compact completed-order sales metrics for a date range."""
    completed_orders = Order.objects.completed_in_date_range(start_date, end_date)
    totals = completed_orders.aggregate(
        total_orders=Count('id'),
        total_amount=Sum('total_amount'),
        total_discount=Sum('discount'),
    )
    total_orders = totals['total_orders'] or 0
    total_amount = totals['total_amount'] or Decimal('0.00')
    total_discount = totals['total_discount'] or Decimal('0.00')
    average_ticket = total_amount / total_orders if total_orders else Decimal('0.00')

    from payment.models import PAYMENT_METHOD_CHOICES, Payment

    method_labels = dict(PAYMENT_METHOD_CHOICES)
    payment_rows = (
        Payment.objects.filter(
            order__in=completed_orders,
            status='completed',
        )
        .exclude(method='pending_credit')
        .values('method')
        .annotate(
            total_amount=Sum('amount'),
            payment_count=Count('id'),
        )
        .order_by('method')
    )
    payment_methods = [
        {
            'method': row['method'],
            'label': method_labels.get(row['method'], row['method']),
            'total_amount': row['total_amount'] or Decimal('0.00'),
            'payment_count': row['payment_count'],
        }
        for row in payment_rows
    ]
    return {
        'total_orders': total_orders,
        'total_amount': total_amount,
        'average_ticket': average_ticket,
        'total_discount': total_discount,
        'payment_methods': payment_methods,
    }


@dataclass
class OrderData:
    id: int
    client_id: int
    total_amount: Decimal
    status: str
    created_at: datetime
    items: List = None


def get_or_create_order(client=None, order_id=None, owner=None) -> OrderData:
    if not client and not order_id:
        raise ValueError("Se requiere un cliente o un ID de orden para obtener o crear una orden.")
    if order_id:
        try:
            order = Order.objects.get(pk=order_id)
            return OrderData(
                id=order.id,
                client_id=order.client_id,
                total_amount=order.total_amount,
                status=order.status,
                created_at=order.created_at,
                items=list(order.items.all())
            )
        except Order.DoesNotExist:
            pass

    existing_orders = get_client_orders(date=date.today(), status=OrderStatus.PENDING, client=client)
    if existing_orders:
        return existing_orders[0]

    order = Order.objects.create(client=client, total_amount=Decimal('0.00'), owner=owner)
    return OrderData(
        id=order.id,
        client_id=order.client_id,
        total_amount=order.total_amount,
        status=order.status,
        created_at=order.created_at,
        items=list(order.items.all())
    )


def get_client_orders(date: date, status: OrderStatus, client: Client) -> List[OrderData]:
    orders = Order.objects.filter(client=client, created_at__date=date, status=status.value)
    return [
        OrderData(
            id=order.id,
            client_id=order.client_id,
            total_amount=order.total_amount,
            status=order.status,
            created_at=order.created_at,
            items=list(order.items.all())
        )
        for order in orders
    ]


def get_product_price_for_client(product, client):
    try:    
        price_entry = ProductClientPrice.objects.get(product=product, client=client)
        return Decimal(str(price_entry.price))
    except ProductClientPrice.DoesNotExist:
        base_price = getattr(product, 'base_price', None)
        if base_price is not None:
            return Decimal(str(base_price))
        return Decimal(str(getattr(product, 'price', 0.0)))
    
def update_order(order: Order, quantity: int, product, client: Client, discount: Decimal = Decimal('0.00')) -> Order:
    unit_price = get_product_price_for_client(product, client)
    if not isinstance(unit_price, Decimal):
        unit_price = Decimal(str(unit_price))
    order.discount = discount

    if quantity <= 0:
        OrderProduct.objects.filter(order=order, product=product).delete()
        order.total_amount = calculate_order_total(order)
        order.save(update_fields=['discount', 'subtotal_amount', 'total_amount'])
        return order

    # Handle potential duplicates due to race conditions or previous bugs
    order_products = list(OrderProduct.objects.filter(order=order, product=product))
    if order_products:
        order_product = order_products[0]
        if len(order_products) > 1:
            # Delete duplicates
            duplicate_ids = [op.pk for op in order_products[1:]]
            OrderProduct.objects.filter(pk__in=duplicate_ids).delete()
    else:
        order_product = OrderProduct.objects.create(
            order=order, 
            product=product, 
            quantity=0, 
            unit_price=unit_price
        )
    order_product.quantity = int(quantity)
    order_product.unit_price = unit_price
    order_product.save()
    # update order totals and return the order
    order.total_amount = calculate_order_total(order)
    order.save(update_fields=['discount', 'subtotal_amount', 'total_amount'])
    return order

def calculate_order_total(order) -> Decimal:
    subtotal = Decimal('0.00')
    for item in order.items.all():
        unit = Decimal(str(item.unit_price))
        qty = Decimal(str(item.quantity))
        subtotal += unit * qty
    discount = Decimal(str(order.discount or 0))
    total = max(Decimal("0"), subtotal - discount)
    if hasattr(order, 'subtotal_amount'):
        order.subtotal_amount = subtotal
    return total

def get_logger(name: str):
    """Return a logger for the orders module.

    This simple helper centralizes logger creation so views can call
    `services.get_logger(__name__)` without needing additional imports.
    """
    return logging.getLogger(name)


@transaction.atomic
def cancel_pending_order(order: Order, user=None) -> Dict[str, object]:
    """Cancel a pending order by deleting it and its related items.

    Returns:
        dict with success status and message/error details.
    """
    if order.status != OrderStatus.PENDING.value:
        return {
            'success': False,
            'error': 'Solo se pueden cancelar pedidos en estado pendiente.',
        }

    if order.payments.exists():
        return {
            'success': False,
            'error': 'No se puede cancelar este pedido porque ya tiene pagos registrados.',
        }

    order_id = order.id
    client_id = order.client_id
    item_count = order.items.count()

    try:
        order.items.all().delete()
        deleted_count, _ = Order.all_objects.filter(pk=order_id).delete()
        if deleted_count == 0:
            return {
                'success': False,
                'error': 'No se pudo eliminar el pedido.',
            }
    except ProtectedError:
        return {
            'success': False,
            'error': 'No se pudo cancelar el pedido porque tiene registros protegidos relacionados.',
        }

    logger.info(
        f"Order #{order_id} cancelled and deleted by "
        f"{user.username if user else 'system'} - client_id={client_id}, items={item_count}"
    )
    return {
        'success': True,
        'message': f'Pedido #{order_id} cancelado correctamente.',
    }


# Payment Processing Functions
# These functions coordinate payment between Client balance/credit and Order


@transaction.atomic
def process_order_payment(
    client: Client,
    order_amount: Decimal,
    payment_method: str = "auto",
    order: Optional[Order] = None,
    user=None,
    credit_note: Optional[str] = None,
) -> dict:
    """
    Process payment for an order using different strategies.

    This function coordinates balance and credit usage but delegates
    the actual mutations to the balance_service.

    Args:
        client: Client making the payment
        order_amount: Amount to process
        payment_method: 'auto', 'balance', 'credit', 'mixed'
        order: Order object for transaction reference
        user: User performing the operation
        credit_note: Optional note appended to the payment notes

    Returns:
        dict with success status and payment breakdown
    """
    from clients.services import balance_service

    remaining_amount = order_amount
    balance_used = Decimal("0")
    credit_used = Decimal("0")
    if payment_method == "balance":
        # Try to pay entirely with balance
        if client.balance >= order_amount:
            balance_used = order_amount
            remaining_amount = Decimal("0")
        else:
            return {
                "success": False,
                "error": f"Insufficient balance. Available: ${client.balance:.2f}, "
                f"Required: ${order_amount:.2f}",
                "balance_used": Decimal("0"),
                "credit_used": Decimal("0"),
            }

    elif payment_method == "credit":
        # Try to pay entirely with credit
        if not client.can_pay_with_credit:
            return {
                "success": False,
                "error": "Cliente no puede pagar con credito",
                "balance_used": Decimal("0"),
                "credit_used": Decimal("0"),
            }

        available_credit = max(
            client.credit_limit - client.current_debt,
            Decimal("0.00"),
        )
        if available_credit >= order_amount:
            credit_used = order_amount
            remaining_amount = Decimal("0")
        else:
            return {
                "success": False,
                "error": f"Insufficient credit. Available: ${available_credit:.2f}, "
                f"Required: ${order_amount:.2f}",
                "balance_used": Decimal("0"),
                "credit_used": Decimal("0"),
            }
    
    else:  # 'auto' or 'mixed'
        # First, use available balance
        balance_used = min(client.balance, remaining_amount)
        remaining_amount -= balance_used

        # Then, use credit if needed and available
        if remaining_amount > 0:
            if not client.can_pay_with_credit:
                return {
                    "success": False,
                    "error": "Cliente no puede pagar con credito",
                    "balance_used": Decimal("0"),
                    "credit_used": Decimal("0"),
                    "balance_available": client.balance,
                    "credit_available": Decimal("0"),
                }

            available_credit = max(
                client.credit_limit - client.current_debt,
                Decimal("0.00"),
            )
            credit_used = min(available_credit, remaining_amount)
            remaining_amount -= credit_used

    # Check if we can cover the full amount
    if remaining_amount > 0:
        return {
            "success": False,
            "error": f"Insufficient funds. Need additional ${remaining_amount:.2f}",
            "balance_used": Decimal("0"),
            "credit_used": Decimal("0"),
            "balance_available": client.balance,
            "credit_available": client.get_available_credit(),
        }

    # Actually process the payment using balance_service
    if balance_used > 0:
        balance_service.deduct_balance(
            client=client,
            amount=balance_used,
            transaction_type="payment",
            user=user,
            reference_order=order,
            notes=f"Pago de orden con saldo - ${balance_used:.2f}",
        )

    if credit_used > 0:
        notes = f"Compra a crédito - ${credit_used:.2f}"
        if credit_note:
            notes = f"{notes}. {credit_note}"
        balance_service.add_debt(
            client=client,
            amount=credit_used,
            transaction_type="purchase",
            user=user,
            reference_order=order,
            notes=notes,
        )

    return {
        "success": True,
        "balance_used": balance_used,
        "credit_used": credit_used,
        "remaining_balance": client.balance,
        "current_debt": client.current_debt,
        "available_credit": client.get_available_credit(),
    }


# Order Status Management Functions
# These functions handle bulk order status transitions with proper audit trails


@transaction.atomic
def mark_orders_as_completed(queryset, user=None) -> Dict[str, int]:
    """
    Mark multiple orders as completed.

    This function:
    1. Validates each order can be completed
    2. Updates status to COMPLETED
    3. Logs the operation with user information

    Args:
        queryset: QuerySet of Order objects to mark as completed
        user: User performing the operation (for audit trail)

    Returns:
        dict with 'updated' count and 'skipped' count
    """
    updated = 0
    skipped = 0

    for order in queryset:
        # Skip if already completed
        if order.status == OrderStatus.COMPLETED.value:
            logger.info(f"Order #{order.id} already completed, skipping")
            skipped += 1
            continue

        # Update status
        order.status = OrderStatus.COMPLETED.value
        order.save(update_fields=['status', 'updated_at'])

        logger.info(
            f"Order #{order.id} marked as COMPLETED by {user.username if user else 'system'}"
        )
        updated += 1

    return {
        'updated': updated,
        'skipped': skipped,
    }


@transaction.atomic
def cancel_orders(queryset, user=None) -> Dict[str, int]:
    """
    Cancel multiple orders.

    This function:
    1. Validates each order can be cancelled
    2. Updates status to CANCELLED
    3. Logs the operation with user information

    Note: Does NOT automatically refund payments. Payment reversal should be
    handled separately through the payment admin if needed.

    Args:
        queryset: QuerySet of Order objects to cancel
        user: User performing the operation (for audit trail)

    Returns:
        dict with 'updated' count and 'skipped' count
    """
    updated = 0
    skipped = 0

    for order in queryset:
        # Skip if already cancelled
        if order.status == OrderStatus.CANCELLED.value:
            logger.info(f"Order #{order.id} already cancelled, skipping")
            skipped += 1
            continue

        # Update status
        order.status = OrderStatus.CANCELLED.value
        order.save(update_fields=['status', 'updated_at'])

        logger.info(
            f"Order #{order.id} marked as CANCELLED by {user.username if user else 'system'}"
        )
        updated += 1

    return {
        'updated': updated,
        'skipped': skipped,
    }


@transaction.atomic
def mark_orders_as_pending(queryset, user=None) -> Dict[str, int]:
    """
    Mark multiple orders as pending.

    This function:
    1. Updates status to PENDING
    2. Logs the operation with user information

    This is typically used to revert orders to pending status for corrections.

    Args:
        queryset: QuerySet of Order objects to mark as pending
        user: User performing the operation (for audit trail)

    Returns:
        dict with 'updated' count and 'skipped' count
    """
    updated = 0
    skipped = 0

    for order in queryset:
        # Skip if already pending
        if order.status == OrderStatus.PENDING.value:
            logger.info(f"Order #{order.id} already pending, skipping")
            skipped += 1
            continue

        # Update status
        order.status = OrderStatus.PENDING.value
        order.save(update_fields=['status', 'updated_at'])

        logger.info(
            f"Order #{order.id} marked as PENDING by {user.username if user else 'system'}"
        )
        updated += 1

    return {
        'updated': updated,
        'skipped': skipped,
    }
