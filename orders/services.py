from decimal import Decimal
from orders.models import Order

def create_order(client):
    order = Order.objects.create(client=client, total_amount=Decimal('0.00'))
    return order