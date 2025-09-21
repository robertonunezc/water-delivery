from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods
from django.db import transaction
from decimal import Decimal

from .models import Order, OrderProduct
from product.models import Product, ProductClientPrice
from clients.models import Client
from orders import services

def create_order(request, client_pk):
    client = get_object_or_404(Client, pk=client_pk)
    order = services.create_order(client)
    products = ProductClientPrice.objects.filter(client=client).prefetch_related('product')
    return render(request, 'create_order.html', {'client': client, 'order': order, 'products': products})

@require_http_methods(["GET", "POST"])
@transaction.atomic
def update_order(request, order_pk):
    order = get_object_or_404(Order, pk=order_pk)
