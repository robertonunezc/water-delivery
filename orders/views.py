from datetime import date
from django.http import JsonResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods
from django.db import transaction
from decimal import Decimal
import json

from .models import Order, OrderProduct, OrderStatus
from product.models import Product, ProductClientPrice
from clients.models import Client
from orders import services
from payment.models import Payment, PAYMENT_METHOD_CHOICES
def create_order(request, client_pk):
    client = get_object_or_404(Client, pk=client_pk)
    order = services.create_order(client)
    client_products = ProductClientPrice.objects.filter(client=client).prefetch_related('product')
    payment_types = PAYMENT_METHOD_CHOICES
    return render(request, 'create_order.html', {'client': client, 'order': order, 'client_products': client_products, 'payment_types': payment_types})

@require_http_methods(["GET", "POST"])
@transaction.atomic
def update_order(request, order_pk):
    order = get_object_or_404(Order, pk=order_pk)
    # get data from request in json format and POST method
    if request.method == 'POST':
        try:
            data = json.loads(request.body.decode('utf-8') or '{}')
        except json.JSONDecodeError:
            return HttpResponseBadRequest('Invalid JSON')

        product_id = data.get('product_id')
        try:
            quantity = int(data.get('quantity', 0))
        except (TypeError, ValueError):
            return HttpResponseBadRequest('Invalid quantity')

        product = get_object_or_404(Product, pk=product_id)
        # Clients should only have one pending order per day
        pending_client_order = services.get_client_orders(date=date.today(), status=OrderStatus.PENDING, client=order.client).first()
        if quantity <= 0:
            pending_client_order.deleted_at = date.today()
            pending_client_order.save()
        else:
           order = services.update_order(pending_client_order, quantity, product, order.client)

        return JsonResponse({'status': 'success', 'order_total': str(order.total_amount)})
