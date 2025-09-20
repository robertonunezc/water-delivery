from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods
from django.db import transaction
from decimal import Decimal

from .models import Order, OrderProduct
from .forms import OrderForm
from product.models import Product, ProductClientPrice
from clients.models import Client


@require_http_methods(["GET", "POST"])
def new_order(request, client_pk):
    client = get_object_or_404(Client, pk=client_pk)
    products = Product.objects.order_by('order')

    if request.method == 'POST':
        form = OrderForm(request.POST)
        # ensure the order is tied to the requested client
        form.instance.client = client

        if form.is_valid():
            with transaction.atomic():
                order = form.save(commit=False)
                total = Decimal('0.00')

                for product in products:
                    qty_key = f'qty_{product.id}'
                    qty_val = request.POST.get(qty_key)
                    try:
                        qty = int(qty_val) if qty_val not in (None, '') else 0
                    except (ValueError, TypeError):
                        qty = 0

                    if qty > 0:
                        price_obj = ProductClientPrice.objects.filter(product=product, client=client).first()
                        unit_price = Decimal(str(price_obj.price)) if price_obj else Decimal('0.00')
                        OrderProduct.objects.create(order=order, product=product, quantity=qty, unit_price=unit_price)
                        total += unit_price * qty

                order.total_amount = total
                order.save()

            return redirect(reverse('orders:detail', args=[order.id]))
    else:
        form = OrderForm(initial={'client': client})

    return render(request, 'orders/new_order.html', {'client': client, 'products': products, 'form': form})