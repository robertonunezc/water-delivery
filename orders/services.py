from datetime import date
from decimal import Decimal
from clients.models import Client
from core import models
from orders.models import Order, OrderStatus


def create_order(client):
    #TODO: decouple this logic from QuerySet and use dataclasses or similar
    if get_client_orders(date=date.today(), status=OrderStatus.PENDING, client=client).exists():
        return get_client_orders(date=date.today(), status=OrderStatus.PENDING, client=client).first()
    order = Order.objects.create(client=client, total_amount=Decimal('0.00'))
    return order

def get_client_orders(date:date , status:OrderStatus, client:Client):
    return Order.objects.filter(client=client, created_at__date=date, status=status.value)

def get_product_price_for_client(product, client):
    from product.models import ProductClientPrice
    try:
        price_entry = ProductClientPrice.objects.get(product=product, client=client)
        return Decimal(str(price_entry.price))
    except ProductClientPrice.DoesNotExist:
        return Decimal(str(getattr(product, 'base_price', 0.0)))
    
def update_order_product(order_product, quantity, product, client):
    unit_price = get_product_price_for_client(product, client)
    if not isinstance(unit_price, Decimal):
        unit_price = Decimal(str(unit_price))

    order_product.quantity = int(quantity)
    order_product.unit_price = unit_price
    order_product.total_price = unit_price * Decimal(order_product.quantity)
    order_product.save()

    # update order total and return the order
    order = order_product.order
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