from datetime import date
from decimal import Decimal
from django.db import transaction
from clients.models import Client
from core import models
from orders.models import Order, OrderProduct, OrderStatus
from product.models import ProductClientPrice
from dataclasses import dataclass
from typing import List, Optional, Dict
from datetime import datetime
import logging

logger = logging.getLogger(__name__)
@dataclass
class OrderData:
    id: int
    client_id: int
    total_amount: Decimal
    status: str
    created_at: datetime
    items: List = None


def create_order(client, owner=None) -> Order:
    #TODO: decouple this logic from QuerySet and use dataclasses or similar
    if get_client_orders(date=date.today(), status=OrderStatus.PENDING, client=client).exists():
        return get_client_orders(date=date.today(), status=OrderStatus.PENDING, client=client).first()
    order = Order.objects.create(client=client, total_amount=Decimal('0.00'), owner=owner)
    return order


def get_client_orders(date: date, status: OrderStatus, client: Client) -> List[OrderData]:
    orders = Order.objects.filter(client=client, created_at__date=date, status=status.value)
    return orders


def get_product_price_for_client(product, client):
    try:    
        price_entry = ProductClientPrice.objects.get(product=product, client=client)
        return Decimal(str(price_entry.price))
    except ProductClientPrice.DoesNotExist:
        return Decimal(str(getattr(product, 'base_price', 0.0)))
    
def update_order(order:Order, quantity:int, product, client:Client, discount: Decimal) -> Order:
    unit_price = get_product_price_for_client(product, client)
    if not isinstance(unit_price, Decimal):
        unit_price = Decimal(str(unit_price))
    order_product, created = OrderProduct.objects.get_or_create(order=order, product=product, defaults={'quantity': 0, 'unit_price': unit_price})
    if quantity <= 0:
        order_product.delete()
        order.total_amount = calculate_order_total(order)
        order.save()
        return order

    order_product.quantity = int(quantity)
    order_product.unit_price = unit_price
    order_product.total_price = unit_price * Decimal(order_product.quantity)
    order_product.save()
    # update order total and return the order
    order.discount = discount
    order.total_amount = calculate_order_total(order)
    order.save()
    return order

def calculate_order_total(order) -> Decimal:
    subtotal = Decimal('0.00')
    for item in order.items.all():
        unit = Decimal(str(item.unit_price))
        qty = Decimal(str(item.quantity))
        subtotal += unit * qty
    discount = Decimal(str(order.discount or 0))
    return max(Decimal("0"), subtotal - discount)

def get_client_order_without_bill(client: Client, no_limit: Optional[int] = None) -> List[OrderData]:
    if no_limit:
        orders = Order.objects.filter(client=client, billing_orders__isnull=True).order_by('-created_at')[:no_limit]
    else:
        orders = Order.objects.filter(client=client, billing_orders__isnull=True).order_by('-created_at')[:10]
    return orders

def get_logger(name: str):
    """Return a logger for the orders module.

    This simple helper centralizes logger creation so views can call
    `services.get_logger(__name__)` without needing additional imports.
    """
    return logging.getLogger(name)


# Payment Processing Functions
# These functions coordinate payment between Client balance/credit and Order


def process_order_payment(
    client: Client,
    order_amount: Decimal,
    preferred_method: str = "auto",
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
        preferred_method: 'auto', 'balance', 'credit', 'mixed'
        order: Order object for transaction reference
        user: User performing the operation
        credit_note: Required note when using credit if client requires it

    Returns:
        dict with success status and payment breakdown
    """
    from clients.services import balance_service

    remaining_amount = order_amount
    balance_used = Decimal("0")
    credit_used = Decimal("0")

    if preferred_method == "balance":
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

    elif preferred_method == "credit":
        # Check if client can use credit
        if not client.can_use_credit_for_payment():
            return {
                "success": False,
                "error": "Client is not allowed to pay with credit at this time.",
                "balance_used": Decimal("0"),
                "credit_used": Decimal("0"),
            }

        # Check if note is required for credit payments
        if client.requires_note_for_credit_payment() and not credit_note:
            return {
                "success": False,
                "error": "A note is required for credit payments for this client.",
                "balance_used": Decimal("0"),
                "credit_used": Decimal("0"),
                "note_required": True,
            }

        # Try to pay entirely with credit
        available_credit = client.get_available_credit()
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
            # Check if client can use credit
            if not client.can_use_credit_for_payment():
                return {
                    "success": False,
                    "error": f"Client cannot use credit. Need additional "
                    f"${remaining_amount:.2f} in balance.",
                    "balance_used": Decimal("0"),
                    "credit_used": Decimal("0"),
                    "balance_available": client.balance,
                    "credit_available": Decimal("0"),
                }

            # Check if note is required for credit payments
            if client.requires_note_for_credit_payment() and not credit_note:
                return {
                    "success": False,
                    "error": "A note is required for credit payments for this client.",
                    "balance_used": Decimal("0"),
                    "credit_used": Decimal("0"),
                    "note_required": True,
                }

            available_credit = client.get_available_credit()
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


def create_payment_for_order(
    client: Client,
    order: Order,
    payment_method: str = "auto",
    user=None,
    credit_note: Optional[str] = None,
) -> dict:
    """
    Create payment records for an order based on how the payment was processed.

    Args:
        client: Client making the payment
        order: Order to create payment for
        payment_method: 'auto', 'balance', 'credit', 'mixed'
        user: User performing the operation
        credit_note: Required note when using credit if client requires it

    Returns:
        dict with success status, payments created, and payment breakdown
    """
    from payment.models import Payment

    order_amount = order.total_amount
    payment_result = process_order_payment(
        client=client,
        order_amount=order_amount,
        preferred_method=payment_method,
        order=order,
        user=user,
        credit_note=credit_note,
    )

    if not payment_result["success"]:
        return {"success": False, "error": payment_result.get("error", "Payment failed")}

    payments_created = []

    # Create balance payment if balance was used
    if payment_result["balance_used"] > 0:
        balance_payment = Payment.objects.create(
            amount=payment_result["balance_used"],
            method="balance",
            client=client,
            order=order,
            status="completed",
            balance_used=payment_result["balance_used"],
        )
        payments_created.append(balance_payment)

    # Create credit payment if credit was used
    if payment_result["credit_used"] > 0:
        credit_payment = Payment.objects.create(
            amount=payment_result["credit_used"],
            method="credit",
            client=client,
            order=order,
            status="completed",
            credit_used=payment_result["credit_used"],
        )
        payments_created.append(credit_payment)

    return {
        "success": True,
        "payments": payments_created,
        "payment_breakdown": payment_result,
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