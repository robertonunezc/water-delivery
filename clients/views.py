from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Count, Q
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.contrib import messages
from datetime import date, datetime, timedelta
from calendar import monthrange
from .models import Client
from .forms import ManualCreditTransactionForm


def calculate_next_billing_date(billing_frequency):
    """Calculate the next billing date based on frequency settings"""
    if not billing_frequency or not billing_frequency.is_active:
        return None
    
    today = date.today()
    
    # Get all possible billing dates from the model
    candidates = billing_frequency.get_next_billing_candidates(today)
    
    if not candidates:
        return None
    
    # Find the first date that is in the future
    for candidate_date in candidates:
        if candidate_date > today:
            # Check if this date matches the frequency pattern
            if _is_valid_billing_date(candidate_date, billing_frequency, today):
                return candidate_date
    
    return None


def _is_valid_billing_date(candidate_date, billing_frequency, reference_date):
    """Check if a candidate date matches the billing frequency pattern"""
    
    # For monthly frequency, any candidate from the model is valid
    if billing_frequency.frequency == 'monthly':
        return True
    
    # For other frequencies, we need to calculate the interval
    interval_months = {
        'bimonthly': 2,
        'quarterly': 3,
        'semiannual': 6,
        'annual': 12,
    }.get(billing_frequency.frequency, 1)
    
    # Check if the candidate date falls on the correct interval
    # This is a simplified check - in a real system you might want to store the last billing date
    month_diff = (candidate_date.year - reference_date.year) * 12 + candidate_date.month - reference_date.month
    return month_diff % interval_months == 0 or month_diff == 1  # Allow next month for monthly


@login_required
def list(request):
    # Get search query from request
    search_query = request.GET.get('search', '').strip()
    
    # Start with all clients
    clients_queryset = Client.objects.select_related().prefetch_related(
        'contacts', 'addresses'
    ).order_by('-created_at', 'name')
    
    # Apply search filter if query exists
    if search_query:
        clients_queryset = clients_queryset.filter(
            Q(name__icontains=search_query) |
            Q(note__icontains=search_query) |
            Q(contacts__name__icontains=search_query) |
            Q(contacts__phone__icontains=search_query) |
            Q(contacts__email__icontains=search_query) |
            Q(addresses__street__icontains=search_query) |
            Q(addresses__city__icontains=search_query) |
            Q(addresses__state__icontains=search_query) |
            Q(billing_data__rfc__icontains=search_query) |
            Q(billing_data__razon_social__icontains=search_query)
        ).distinct()
    
    # Pagination
    paginator = Paginator(clients_queryset, 10)  # Show 10 clients per page
    page = request.GET.get('page')
    
    try:
        clients = paginator.page(page)
    except PageNotAnInteger:
        # If page is not an integer, deliver first page.
        clients = paginator.page(1)
    except EmptyPage:
        # If page is out of range (e.g. 9999), deliver last page of results.
        clients = paginator.page(paginator.num_pages)
    
    context = {
        'clients': clients,
        'search_query': search_query,
        'total_clients': paginator.count,
        'has_search': bool(search_query),
    }
    
    return render(request, 'list_clients.html', context)

@login_required
def detail(request, pk):
    client = get_object_or_404(Client, pk=pk)
    first_day_of_month = date.today().replace(day=1)
    # Get client's orders with related data
    orders = client.orders.all().prefetch_related('items__product', 'payments').order_by('-created_at')
    
    # Get client's payments with related data
    payments = client.payments.filter(date__gte=first_day_of_month).select_related('order').order_by('-date')
    
    # Get credit and balance transactions
    balance_transactions = client.balance_transactions.all().select_related('reference_order', 'reference_payment', 'created_by').order_by('-created_at')
    credit_transactions = client.credit_transactions.all().select_related('reference_order', 'reference_payment', 'created_by').order_by('-created_at')
    
    # Combine all payment-related data for the recent transactions view
    all_payment_data = []
    
    # Add regular payments
    for payment in payments:
        all_payment_data.append({
            'type': 'payment',
            'id': payment.id,
            'date': payment.date,
            'amount': payment.amount,
            'method': payment.get_method_display(),
            'status': payment.get_status_display(),
            'status_class': 'success' if payment.status == 'completed' else 'warning' if payment.status == 'pending' else 'danger',
            'order_id': payment.order.id if payment.order else None,
            'description': f'Pago de orden #{payment.order.id}' if payment.order else 'Pago general',
            'is_positive': True,  # Regular payments are always positive from client perspective
            'object': payment
        })
    
    # Add balance transactions  
    for balance_tx in balance_transactions:
        # Skip balance transactions that are already represented as payments
        if balance_tx.reference_payment:
            continue
            
        status_class = 'success' if balance_tx.transaction_type in ['deposit', 'refund', 'transfer_in'] else 'info'
        is_positive = balance_tx.transaction_type in ['deposit', 'refund', 'transfer_in', 'adjustment']
        all_payment_data.append({
            'type': 'balance_transaction',
            'id': balance_tx.id,
            'date': balance_tx.created_at,
            'amount': balance_tx.amount,
            'method': balance_tx.get_transaction_type_display(),
            'status': 'Completado',
            'status_class': status_class,
            'order_id': balance_tx.reference_order.id if balance_tx.reference_order else None,
            'description': balance_tx.notes or balance_tx.get_transaction_type_display(),
            'is_positive': is_positive,
            'object': balance_tx
        })
    
    # Add credit transactions
    for credit_tx in credit_transactions:
        # Skip credit transactions that are already represented as payments
        if credit_tx.reference_payment:
            continue
            
        status_class = 'warning' if credit_tx.transaction_type in ['purchase', 'interest', 'fee'] else 'success'
        is_positive = credit_tx.transaction_type in ['payment', 'adjustment', 'forgiveness', 'correction']
        all_payment_data.append({
            'type': 'credit_transaction',
            'id': credit_tx.id,
            'date': credit_tx.created_at,
            'amount': credit_tx.amount,
            'method': credit_tx.get_transaction_type_display(),
            'status': 'Completado',
            'status_class': status_class,
            'order_id': credit_tx.reference_order.id if credit_tx.reference_order else None,
            'description': credit_tx.notes or credit_tx.get_transaction_type_display(),
            'is_positive': is_positive,
            'object': credit_tx
        })
    
    # Sort all payment data by date (most recent first)
    all_payment_data.sort(key=lambda x: x['date'], reverse=True)
    
    # Calculate client statistics
    total_orders = orders.count()
    total_spent = payments.filter(status='completed').aggregate(total=Sum('amount'))['total'] or 0
    pending_orders = orders.filter(status='pending').count()
    completed_orders = orders.filter(status='completed').count()
    
    # Get client's contacts and addresses
    contacts = client.contacts.all()
    addresses = client.addresses.filter(active=True)
    billing_data = client.billing_data.all()
    
    # Get billing frequency information
    billing_frequencies = client.billing_frecuency.all()
    billing_frequency_info = None
    next_billing_date = None
    
    if billing_frequencies.exists():
        billing_frequency = billing_frequencies.first()  # Assuming one billing frequency per client
        billing_frequency_info = billing_frequency
        next_billing_date = calculate_next_billing_date(billing_frequency)
    
    # Get route information for the client
    route_clients = client.client_routes.filter(is_active=True).select_related(
        'route__transportation__assigned_driver__user',
        'route'
    ).order_by('sequence')
    
    # Get upcoming route client orders (specific deliveries)
    today = date.today()
    upcoming_route_orders = client.client_route_orders.filter(
        visit_date__gte=today,
        is_completed=False
    ).select_related(
        'route__transportation__assigned_driver__user',
        'route',
        'order'
    ).order_by('visit_date')[:10]  # Limit to next 10 upcoming visits
    
    # Get recent completed route orders for reference
    recent_completed_routes = client.client_route_orders.filter(
        is_completed=True
    ).select_related(
        'route__transportation__assigned_driver__user',
        'route',
        'order'
    ).order_by('-completed_at')[:5]  # Last 5 completed deliveries
    
    context = {
        'client': client,
        'date_since': first_day_of_month,
        'orders': orders[:10],  # Limit to recent 10 orders for performance
        'payments': payments[:10],  # Limit to recent 10 payments for backward compatibility
        'all_payment_data': all_payment_data[:10],  # Combined payment data - limit to recent 10
        'contacts': contacts,
        'addresses': addresses,
        'billing_data': billing_data,
        'billing_frequency': billing_frequency_info,
        'next_billing_date': next_billing_date,
        'route_clients': route_clients,
        'upcoming_route_orders': upcoming_route_orders,
        'recent_completed_routes': recent_completed_routes,
        'stats': {
            'total_orders': total_orders,
            'total_spent': total_spent,
            'pending_orders': pending_orders,
            'completed_orders': completed_orders,
        }
    }
    
    return render(request, 'client_detail.html', context)


@login_required
def pay_credit(request, pk):
    """View for paying credit (reducing debt) for a client"""
    client = get_object_or_404(Client, pk=pk)
    
    if request.method == 'POST':
        form = ManualCreditTransactionForm(request.POST)
        if form.is_valid():
            amount = form.cleaned_data['amount']
            transaction_type = form.cleaned_data['transaction_type']
            description = form.cleaned_data['description']
            notes = form.cleaned_data['notes']
            new_credit_limit = form.cleaned_data.get('new_credit_limit')
            
            try:
                if transaction_type == 'limit_change':
                    # Update credit limit
                    client.update_credit_limit(
                        new_limit=new_credit_limit,
                        user=request.user,
                        notes=f"{description}. {notes}"
                    )
                    messages.success(
                        request,
                        f"Límite de crédito actualizado exitosamente. {client.name} ahora tiene ${client.credit_limit:.2f} de límite."
                    )
                
                elif transaction_type in ['payment', 'forgiveness', 'adjustment', 'correction']:
                    # Pay down debt
                    paid_amount = client.pay_debt(
                        amount=amount,
                        transaction_type=transaction_type,
                        user=request.user,
                        notes=f"{description}. {notes}"
                    )
                    messages.success(
                        request,
                        f"Pago aplicado exitosamente. Deuda reducida en ${paid_amount:.2f}. {client.name} ahora debe ${client.current_debt:.2f}."
                    )
                
                elif transaction_type == 'payment_from_balance':
                    # Pay debt using client's balance
                    result = client.pay_debt_from_balance(
                        amount=amount,
                        user=request.user,
                        notes=f"{description}. {notes}"
                    )
                    if result['success']:
                        messages.success(
                            request,
                            f"Pago con saldo exitoso. ${result['amount_paid']:.2f} descontados del saldo. "
                            f"Saldo restante: ${result['remaining_balance']:.2f}. "
                            f"Deuda restante: ${result['remaining_debt']:.2f}."
                        )
                    else:
                        messages.error(request, f"Error en pago con saldo: {result['error']}")
                        return render(request, 'pay_credit.html', {
                            'form': form,
                            'client': client,
                        })
                
                return redirect('clients:detail', pk=client.pk)
                
            except Exception as e:
                messages.error(request, f"Error al procesar la transacción: {str(e)}")
    else:
        # Initialize form with the client pre-selected and default to 'payment'
        form = ManualCreditTransactionForm(initial={'client': client, 'transaction_type': 'payment'})
        # Make client field readonly by disabling it
        form.fields['client'].widget.attrs['disabled'] = True
        form.fields['client'].required = False
    
    context = {
        'form': form,
        'client': client,
    }
    
    return render(request, 'pay_credit.html', context)