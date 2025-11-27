from datetime import date
from decimal import Decimal
from clients.models import Client
from core import models
from orders.models import Order, OrderProduct, OrderStatus
from product.models import ProductClientPrice
from dataclasses import dataclass
from typing import List, Optional
from datetime import datetime
import logging
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
    
def update_order(order, quantity, product, client):
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
    order.total_amount = calculate_order_total(order)
    order.save()
    return order

def calculate_order_total(order):
    total = Decimal('0.00')
    for item in order.items.all():
        unit = Decimal(str(item.unit_price))
        qty = Decimal(str(item.quantity))
        total += unit * qty
    return total


def get_logger(name: str):
    """Return a logger for the orders module.

    This simple helper centralizes logger creation so views can call
    `services.get_logger(__name__)` without needing additional imports.
    """
    return logging.getLogger(name)