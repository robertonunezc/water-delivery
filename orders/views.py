from datetime import date, timedelta
from botocore import client
from django.contrib import messages
from django.contrib.auth.models import AbstractBaseUser
from django.http import JsonResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.core.paginator import Paginator
from django.db.models import Q, Sum, Count, Prefetch
from decimal import Decimal
import json

from .models import Order, OrderProduct, OrderStatus, ORDER_STATUS_CHOICES, OrderSplit
from .forms import SplitOrderForm
from product.models import Product, ProductClientPrice
from clients.models import Client
from .  import services as order_services
from payment.models import Payment, PAYMENT_METHOD_CHOICES
from payment import services as payment_services
from routes import services as route_services

log = order_services.get_logger(__name__)

ORDER_DASHBOARD_BULK_ACTIONS = (
    {
        'value': 'create_invoice',
        'label': 'Crear factura',
    },
    # {
    #     'value': 'mark_completed',
    #     'label': 'Marcar como completados',
    # },
    # {
    #     'value': 'mark_pending',
    #     'label': 'Marcar como pendientes',
    # },
    # {
    #     'value': 'mark_cancelled',
    #     'label': 'Marcar como cancelados',
    # },
)

ROUTE_REDIRECT_EMPLOYEE_POSITIONS = {'staff', 'driver'}


def _should_redirect_order_to_route(user: AbstractBaseUser) -> bool:
    employee = getattr(user, 'employee', None)
    return bool(employee and employee.position in ROUTE_REDIRECT_EMPLOYEE_POSITIONS)


def _get_order_redirect_url(user: AbstractBaseUser, client: Client) -> str:
    if not _should_redirect_order_to_route(user):
        return reverse('clients:list')

    route = route_services.get_current_route_for_client(client)
    if route is None:
        return reverse('clients:list')

    return reverse('routes:detail', kwargs={'route_id': route.pk})


def calculate_payment_breakdown(order_total, client_balance):
    """
    Calculate how an order should be paid based on available client balance.
    
    Rules:
    - If client has balance >= order total: pay entirely with balance
    - If client has balance < order total: use all balance, pay rest with other method
    - If client has no balance: pay entirely with other method
    
    Returns:
        dict: Payment breakdown with balance_amount, remaining_amount, and use_balance flag
    """
    order_total = Decimal(str(order_total))
    client_balance = Decimal(str(client_balance))
    
    if client_balance <= 0:
        # No balance available
        return {
            'use_balance': False,
            'balance_amount': '0.00',
            'remaining_amount': str(order_total),
            'balance_covers_order': False,
            'message': 'Sin saldo disponible. Pago completo con otro método.'
        }
    elif client_balance >= order_total:
        # Balance covers the entire order
        return {
            'use_balance': True,
            'balance_amount': str(order_total),
            'remaining_amount': '0.00',
            'balance_covers_order': True,
            'message': f'Pago completo con saldo disponible (${order_total:.2f})'
        }
    else:
        # Partial payment with balance
        remaining = order_total - client_balance
        return {
            'use_balance': True,
            'balance_amount': str(client_balance),
            'remaining_amount': str(remaining),
            'balance_covers_order': False,
            'message': f'Saldo: ${client_balance:.2f} + Otro método: ${remaining:.2f}'
        }

@login_required
@require_http_methods(["GET", "POST"])
def create_payment_for_order(request, order_pk):
    order = get_object_or_404(Order, pk=order_pk)
    pending_credit = order.payments.filter(
        method='pending_credit',
        status='pending',
    ).first()
    
    if request.method == "POST":
        try:
            data = json.loads(request.body.decode('utf-8') or '{}')
        except json.JSONDecodeError:
            return HttpResponseBadRequest('Invalid JSON')

        amount = Decimal(str(data.get('amount', '0')))
        if amount <= 0:
            return JsonResponse({'success': False, 'error': 'El monto debe ser mayor a 0.'}, status=400)
        
        payment_method = data.get('payment_method', 'cash')
        valid_payment_methods = [value for value, label in PAYMENT_METHOD_CHOICES]
        if payment_method not in valid_payment_methods:
            return JsonResponse({'success': False, 'error': 'Método de pago inválido.'}, status=400)

        try:
            if pending_credit:
                payment, error = payment_services.settle_credit_order_payment(
                    order=order,
                    payment_method=payment_method,
                    amount=amount,
                    request_user=request.user,
                )
            else:
                payment, error = payment_services.process_single_payment(
                    order=order,
                    payment_method=payment_method,
                    amount=amount,
                    request_user=request.user,
                )
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=400)
        if error:
            return JsonResponse({'success': False, 'error': error['error']}, status=400)
        
        return JsonResponse({'success': True, 'message': 'Pago creado exitosamente.'})
    # GET request
    payment_amount = pending_credit.amount if pending_credit else order.total_amount
    payment_breakdown = calculate_payment_breakdown(payment_amount, order.client.balance)
    payment_types = [
        (value, label)
        for value, label in PAYMENT_METHOD_CHOICES
        if value not in {'credit', 'pending_credit', 'other'}
    ]
    context = {
        'order': order,
        'payment_amount': payment_amount,
        'payment_breakdown': payment_breakdown,
        'payment_types': payment_types,
    }
    return render(request, 'admin/orders/pay.html', context)

@login_required
def list_orders(request):
    """List all orders with comprehensive filtering options."""
    context = _build_orders_list_context(request, per_page=15)
    return render(request, 'orders/list_order.html', context)


@staff_member_required
def list_orders_admin(request):
    """List orders for the custom administrador dashboard view."""
    if request.method == 'POST':
        return _handle_orders_dashboard_bulk_action(request)

    context = _build_orders_list_context(request, per_page=15)
    return render(request, 'admin/orders/pedidos_list.html', context)


def _handle_orders_dashboard_bulk_action(request):
    """Handle bulk actions submitted from the dashboard order list."""
    action = request.POST.get('bulk_action', '')
    selected_ids = request.POST.getlist('selected_orders')
    redirect_to = request.get_full_path() or reverse('admin_orders')

    if not action:
        messages.error(request, 'Selecciona una acción para continuar.')
        return redirect(redirect_to)

    if not selected_ids:
        messages.error(request, 'Selecciona al menos un pedido.')
        return redirect(redirect_to)

    selected_orders = list(
        Order.objects.filter(pk__in=selected_ids)
        .select_related('client')
        .prefetch_related('items', 'payments')
    )

    if not selected_orders:
        messages.error(request, 'No se encontraron pedidos válidos para procesar.')
        return redirect(redirect_to)

    if action == 'create_invoice':
        return _handle_create_invoice_action(request, selected_orders, redirect_to)

    if action == 'mark_completed':
        result = order_services.mark_orders_as_completed(selected_orders, user=request.user)
        messages.success(
            request,
            f"{result['updated']} pedido(s) marcados como completados."
            + (f" {result['skipped']} ya estaban completados." if result['skipped'] else ''),
        )
        return redirect(redirect_to)

    if action == 'mark_pending':
        result = order_services.mark_orders_as_pending(selected_orders, user=request.user)
        messages.success(
            request,
            f"{result['updated']} pedido(s) marcados como pendientes."
            + (f" {result['skipped']} ya estaban pendientes." if result['skipped'] else ''),
        )
        return redirect(redirect_to)

    if action == 'mark_cancelled':
        result = order_services.cancel_orders(selected_orders, user=request.user)
        review_message = (
            f" {result['review_required']} requiere(n) revisión."
            if result.get('review_required')
            else ''
        )
        messages.success(
            request,
            f"{result['updated']} pedido(s) marcados como cancelados."
            + (f" {result['skipped']} no se cancelaron." if result['skipped'] else '')
            + review_message,
        )
        return redirect(redirect_to)

    messages.error(request, 'Acción no reconocida.')
    return redirect(redirect_to)


def _handle_create_invoice_action(request, selected_orders, redirect_to):
    """Validate selected orders and create an invoice from them."""
    from invoice.models import InvoiceOrderLink
    from invoice.services import create_invoice_from_orders

    non_completed = [order for order in selected_orders if order.status != OrderStatus.COMPLETED.value]
    if non_completed:
        ids = ', '.join(f'#{order.id}' for order in non_completed)
        messages.error(
            request,
            f'Solo se pueden facturar pedidos completados. Pedidos no completados: {ids}',
        )
        return redirect(redirect_to)

    clients = {order.client for order in selected_orders}
    #Validate if all clients are corporate and if are branches they must belong to the same corporate
    clients_corporate = []
    
    for client in clients:
        if client.corporate is not None:
            clients_corporate.append(client.corporate)
        else:
            clients_corporate.append(client)

    if len(set(clients_corporate)) > 1:
        messages.error(request, 'Todos los pedidos seleccionados deben pertenecer al mismo cliente corporativo.')
        return redirect(redirect_to)

    already_billed_ids = list(
        InvoiceOrderLink.objects.filter(order__in=selected_orders).values_list('order_id', flat=True)
    )
    if already_billed_ids:
        ids = ', '.join(f'#{order_id}' for order_id in already_billed_ids)
        messages.error(request, f'Los siguientes pedidos ya están facturados: {ids}')
        return redirect(redirect_to)

    client = selected_orders[0].client

    try:
        invoice = create_invoice_from_orders(orders=selected_orders, client=client)
    except ValidationError as exc:
        messages.error(request, str(exc))
        return redirect(redirect_to)

    messages.success(
        request,
        f'Factura #{invoice.id} creada para {client.name} por ${invoice.amount}. '
        'Actualiza el identificador y folio antes de emitirla.',
    )
    return redirect(reverse('admin_edit_invoice', args=[invoice.id]))


def _build_orders_list_context(request, per_page: int = 15) -> dict:
    """Build context for order listing views with shared filters and pagination."""
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
        if status_filter == 'PAID':
            orders = orders.paid()
        elif status_filter == 'UNPAID':
            orders = orders.unpaid()
        elif status_filter == 'REVIEW_REQUIRED':
            orders = orders.review_required()
        else:
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
    paginator = Paginator(orders, per_page)
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
    
    # Extend status choices with virtual statuses
    extended_status_choices = list(ORDER_STATUS_CHOICES)
    extended_status_choices.extend([
        ('REVIEW_REQUIRED', 'Requiere revisión'),
        ('PAID', 'Pagados'),
        ('UNPAID', 'No pagados')
    ])
    review_required_count = Order.objects.review_required().count()
    
    return {
        'orders': orders_page,
        'status_choices': extended_status_choices,
        'bulk_actions': ORDER_DASHBOARD_BULK_ACTIONS,
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
        'review_required_count': review_required_count,
        'page_stats': page_stats,
        'today': date.today(),
    }


@login_required
def get_or_create_order(request, client_pk=None, order_id=None):
    if order_id is not None:
        order_data = order_services.get_or_create_order(order_id=order_id)
        client = get_object_or_404(Client, pk=order_data.client_id)
        order = get_object_or_404(Order, pk=order_data.id)
    else:
        client = get_object_or_404(Client, pk=client_pk)
        owner = request.user
        order_data = order_services.get_or_create_order(client, owner=owner)
        order = get_object_or_404(Order, pk=order_data.id)

    owner = request.user
    client_products = client.get_products()
    payment_types = [
        (value, label)
        for value, label in PAYMENT_METHOD_CHOICES
        if value not in {'credit', 'pending_credit'}
    ]
    # Calculate initial payment breakdown based on client balance and order total
    initial_breakdown = calculate_payment_breakdown(order.total_amount, client.balance)
    has_delivery_address = client.addresses.filter(type='delivery').exists()
    has_pending_credit_payment = order.payments.filter(method='pending_credit', status='pending').exists()

    context = {
        'client': client, 
        'order': order, 
        'client_products': client_products, 
        'payment_types': payment_types,
        'order_type': order.type,
        'has_pending_credit_payment': has_pending_credit_payment,
        'initial_payment_breakdown': json.dumps(initial_breakdown),
        'has_delivery_address': has_delivery_address,
        'order_redirect_url': _get_order_redirect_url(request.user, client),
    }
    log.info(
        f"Opened order id:{order.id} for client {client.id} by user {owner.username}"
    )
    
    return render(request, 'create_order.html', context)

@login_required
@require_http_methods(["POST"])
@transaction.atomic
def update_order(request, order_pk):
    order = get_object_or_404(Order, pk=order_pk)
    try:
        data = json.loads(request.body.decode('utf-8') or '{}')
    except json.JSONDecodeError:
        return HttpResponseBadRequest('Invalid JSON')

    quantity = None
    discount = None
    product_id = data.get('product_id')
    notes = data.get('notes')

    try:
        if 'quantity' in data:
            quantity = int(data.get('quantity', 0))
        if 'discount' in data:
            discount = Decimal(str(data.get('discount', '0')))
    except (TypeError, ValueError):
        return HttpResponseBadRequest('Invalid quantity or discount format')

    if notes is not None:
        order.notes = notes.strip() or None

    if product_id:
        if quantity is None:
            return HttpResponseBadRequest('Missing quantity')
        product = get_object_or_404(Product, pk=product_id)
        effective_discount = discount if discount is not None else order.discount
        order = order_services.update_order(
            order,
            quantity,
            product,
            order.client,
            effective_discount,
        )
        if notes is not None:
            order.save(update_fields=['notes', 'updated_at'])
    elif discount is not None:
        order.discount = discount
        order.total_amount = order_services.calculate_order_total(order)
        update_fields = ['discount', 'subtotal_amount', 'total_amount']
        if notes is not None:
            update_fields.append('notes')
        order.save(update_fields=update_fields)
    elif notes is not None:
        order.save(update_fields=['notes', 'updated_at'])

    client = order.client
    order_total = order.total_amount
    client_balance = client.balance
    payment_breakdown = calculate_payment_breakdown(order_total, client_balance)

    return JsonResponse({
        'status': 'success',
        'order_total': str(order.total_amount),
        'subtotal': str(order.subtotal_amount),
        'client_balance': str(client_balance),
        'discount': str(order.discount),
        'notes': order.notes or '',
        'payment_breakdown': payment_breakdown
    })


@login_required
@require_http_methods(["POST"])
def cancel_order(request, order_pk):
    order = get_object_or_404(Order, pk=order_pk)
    result = order_services.cancel_order(order=order, user=request.user)

    if not result.get('success'):
        return JsonResponse(
            {
                'success': False,
                'review_required': bool(result.get('review_required')),
                'error': result.get('error', 'No se pudo cancelar el pedido.'),
            },
            status=400,
        )

    return JsonResponse({
        'success': True,
        'message': result.get('message', 'Pedido cancelado correctamente.'),
        'redirect_url': reverse('clients:list'),
    })


@login_required
@require_http_methods(["GET", "POST"])
@transaction.atomic
def split_order(request, order_id):
    """View to split an order into two orders"""
    order = get_object_or_404(Order.objects.prefetch_related('items__product'), pk=order_id)
    order_items = order.items.all()
    
    if request.method == 'POST':
        form = SplitOrderForm(request.POST, order=order)
        
        if form.is_valid():
            # Create the new order
            new_order = Order.objects.create(
                client=order.client,
                order_date=order.order_date,
                status=order.status,
                total_amount=Decimal('0.00'),  # Will be calculated
                cantidad_cobrada=None,  # Will be calculated
                owner=order.owner,
                notes=f'Dividida de Orden #{order.id}'
            )
            
            # Track amounts for proportional cantidad_cobrada split
            original_total = Decimal('0.00')
            new_total = Decimal('0.00')
            
            # Process each item
            new_order_products = []
            items_to_update = []
            items_to_delete = []

            for item in order_items:
                field_name = f'quantity_{item.id}'
                quantity_to_move = form.cleaned_data.get(field_name, 0)
                
                if quantity_to_move > 0:
                    # Collect item for new order
                    new_order_products.append(
                        OrderProduct(
                            order=new_order,
                            product=item.product,
                            quantity=quantity_to_move,
                            unit_price=item.unit_price,
                            note=item.note
                        )
                    )
                    
                    # Calculate amounts
                    new_total += quantity_to_move * item.unit_price
                    
                    # Update original order item
                    remaining_quantity = item.quantity - quantity_to_move
                    if remaining_quantity > 0:
                        item.quantity = remaining_quantity
                        items_to_update.append(item)
                        original_total += remaining_quantity * item.unit_price
                    else:
                        # Collect item to remove if quantity is 0
                        items_to_delete.append(item.id)

            if new_order_products:
                OrderProduct.objects.bulk_create(new_order_products)
            
            if items_to_update:
                OrderProduct.objects.bulk_update(items_to_update, ['quantity'])

            if items_to_delete:
                OrderProduct.objects.filter(id__in=items_to_delete).delete()

            # Update totals
            order.total_amount = original_total
            new_order.total_amount = new_total
            
            # Split cantidad_cobrada proportionally if it exists
            if order.cantidad_cobrada is not None and order.cantidad_cobrada > 0:
                original_order_total = original_total + new_total
                if original_order_total > 0:
                    # Store the original cantidad_cobrada before modifying
                    original_cantidad_cobrada = order.cantidad_cobrada
                    
                    # Calculate proportional split
                    proportion_original = original_total / original_order_total
                    proportion_new = new_total / original_order_total
                    
                    order.cantidad_cobrada = (original_cantidad_cobrada * proportion_original).quantize(Decimal('0.01'))
                    new_order.cantidad_cobrada = (original_cantidad_cobrada * proportion_new).quantize(Decimal('0.01'))
            
            order.save()
            new_order.save()
            
            # Handle payments - split them proportionally
            original_payments = Payment.objects.filter(order=order, status='completed')
            if original_payments.exists():
                original_order_total = original_total + new_total
                if original_order_total > 0:
                    proportion_original = original_total / original_order_total
                    proportion_new = new_total / original_order_total
                    
                    for payment in original_payments:
                        # Store original amount before modifying
                        original_amount = payment.amount
                        original_balance_used = payment.balance_used
                        original_credit_used = payment.credit_used
                        
                        # Calculate proportional amounts
                        original_payment_amount = (original_amount * proportion_original).quantize(Decimal('0.01'))
                        new_payment_amount = (original_amount * proportion_new).quantize(Decimal('0.01'))
                        
                        # Create new payment for the new order (skip processing by setting status after creation)
                        new_payment = Payment(
                            order=new_order,
                            client=new_order.client,
                            amount=new_payment_amount,
                            method=payment.method,
                            status='pending',  # Set as pending first to avoid triggering save logic
                            balance_used=(original_balance_used * proportion_new).quantize(Decimal('0.01')) if original_balance_used else Decimal('0.00'),
                            credit_used=(original_credit_used * proportion_new).quantize(Decimal('0.01')) if original_credit_used else Decimal('0.00'),
                            created_by=request.user
                        )
                        new_payment.save()
                        # Now update status to completed without triggering balance/credit logic
                        Payment.objects.filter(pk=new_payment.pk).update(status='completed')
                        
                        # Update the original payment amount directly to avoid triggering save logic
                        Payment.objects.filter(pk=payment.pk).update(
                            amount=original_payment_amount,
                            balance_used=(original_balance_used * proportion_original).quantize(Decimal('0.01')) if original_balance_used else Decimal('0.00'),
                            credit_used=(original_credit_used * proportion_original).quantize(Decimal('0.01')) if original_credit_used else Decimal('0.00')
                        )
            
            # Create split record for tracking
            OrderSplit.objects.create(
                source_order=order,
                child_order=new_order,
                split_by=request.user
            )
            
            # Redirect back to admin with success message
            from django.contrib import messages
            messages.success(
                request,
                f'Orden dividida exitosamente. Nueva orden #{new_order.id} creada con total ${new_order.total_amount}. '
                f'Orden original #{order.id} actualizada con total ${order.total_amount}.'
            )
            
            return redirect('admin:orders_order_change', order.id)
    else:
        form = SplitOrderForm(order=order)
    
    # Create a list pairing items with their form fields
    items_with_fields = []
    for item in order_items:
        field_name = f'quantity_{item.id}'
        items_with_fields.append({
            'item': item,
            'field': form[field_name] if field_name in form.fields else None
        })
    
    context = {
        'form': form,
        'order': order,
        'items': order_items,
        'items_with_fields': items_with_fields,
        'title': f'Dividir Orden #{order.id}',
    }
    
    return render(request, 'admin/orders/split_order.html', context)

@login_required
def client_order_history(request, client_pk):
    client = get_object_or_404(Client, pk=client_pk)
    orders = Order.objects.filter(client=client).order_by('-order_date', '-id')
    
    paginator = Paginator(orders, 15)  # Show 15 orders per page
    page_number = request.GET.get('page', 1)
    orders_page = paginator.get_page(page_number)
    
    context = {
        'client': client,
        'orders': orders_page,
    }
    
    return render(request, 'orders/client_order_history.html', context)
