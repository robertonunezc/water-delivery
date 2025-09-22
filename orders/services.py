from datetime import date
from decimal import Decimal
from clients.models import Client
from orders.models import Order, OrderStatus


def create_order(client):
    #TODO: decouple this logic from QuerySet and use dataclasses or similar
    if get_client_orders(date=date.today(), status=OrderStatus.PENDING, client=client).exists():
        return get_client_orders(date=date.today(), status=OrderStatus.PENDING, client=client).first()
    order = Order.objects.create(client=client, total_amount=Decimal('0.00'))
    return order

def get_client_orders(date:date , status:OrderStatus, client:Client):
    return Order.objects.filter(client=client, created_at__date=date, status=status.value)