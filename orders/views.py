from datetime import date, timedelta
from django.http import JsonResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.core.paginator import Paginator
from django.db.models import Q, Sum, Count, Prefetch
from decimal import Decimal
import json

from .models import Order, OrderProduct, OrderStatus, ORDER_STATUS_CHOICES
from product.models import Product, ProductClientPrice
from clients.models import Client
from orders import services
from payment.models import Payment, PAYMENT_METHOD_CHOICES


@login_required
def list_orders(request):
    """List all orders with comprehensive filtering options"""
    # Base queryset with optimized queries
    orders = Order.objects.select_related('client').prefetch_related(
        Prefetch('items', queryset=OrderProduct.objects.select_related('product')),
        'client__contacts',
        'client__addresses'
    )
    
    # Apply filters
    status_filter = request.GET.get('status', '')
    client_filter = request.GET.get('client', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    search_query = request.GET.get('search', '').strip()
    
    # Status filter
    if status_filter:
        orders = orders.filter(status=status_filter)
    
    # Client filter
    if client_filter:
        try:
            client_id = int(client_filter)
            orders = orders.filter(client_id=client_id)
        except (ValueError, TypeError):
            pass
    
    # Date range filter
    if date_from:
        try:
            from datetime import datetime
            date_from_obj = datetime.strptime(date_from, '%Y-%m-%d').date()
            orders = orders.filter(order_date__date__gte=date_from_obj)
        except ValueError:
            pass
    
    if date_to:
        try:
            from datetime import datetime
            date_to_obj = datetime.strptime(date_to, '%Y-%m-%d').date()
            orders = orders.filter(order_date__date__lte=date_to_obj)
        except ValueError:
            pass
    
    # Search functionality
    if search_query:
        orders = orders.filter(
            Q(client__name__icontains=search_query) |
            Q(notes__icontains=search_query) |
            Q(items__product__name__icontains=search_query) |
            Q(id__icontains=search_query)
        ).distinct()
    
    # Order by most recent first
    orders = orders.order_by('-order_date', '-id')
    
    # Get filter options for dropdowns
    all_clients = Client.objects.filter(orders__isnull=False).distinct().order_by('name')
    
    # Calculate summary statistics
    total_orders = orders.count()
    
    # Pagination
    paginator = Paginator(orders, 15)  # Show 15 orders per page
    page_number = request.GET.get('page', 1)
    orders_page = paginator.get_page(page_number)
    
    # Calculate page statistics
    orders_on_page = orders_page.object_list
    if orders_on_page:
        page_stats = orders_on_page.aggregate(
            total_amount=Sum('total_amount'),
            count=Count('id')
        )
    else:
        page_stats = {'total_amount': 0, 'count': 0}
    
    context = {
        'orders': orders_page,
        'status_choices': ORDER_STATUS_CHOICES,
        'all_clients': all_clients,
        'filters': {
            'status': status_filter,
            'client': client_filter,
            'date_from': date_from,
            'date_to': date_to,
            'search': search_query,
        },
        'has_filters': any([status_filter, client_filter, date_from, date_to, search_query]),
        'total_orders': total_orders,
        'page_stats': page_stats,
        'today': date.today(),
    }
    
    return render(request, 'orders/list_order.html', context)


@login_required
def create_order(request, client_pk):
    client = get_object_or_404(Client, pk=client_pk)
    order = services.create_order(client)
    client_products = ProductClientPrice.objects.filter(client=client).prefetch_related('product')
    payment_types = PAYMENT_METHOD_CHOICES
    
    # Add client credit payment settings for frontend validation
    context = {
        'client': client, 
        'order': order, 
        'client_products': client_products, 
        'payment_types': payment_types,
        'can_use_credit': client.can_use_credit_for_payment(),
        'requires_credit_note': client.requires_note_for_credit_payment(),
    }
    
    return render(request, 'create_order.html', context)


@login_required
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
