from django.shortcuts import render, get_object_or_404
from django.db.models import Sum, Count, Q
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from datetime import date, datetime, timedelta
from calendar import monthrange
from .models import Client


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

def detail(request, pk):
    client = get_object_or_404(Client, pk=pk)
    
    # Get client's orders with related data
    orders = client.orders.all().prefetch_related('items__product', 'payments').order_by('-created_at')
    
    # Get client's payments with related data
    payments = client.payments.all().select_related('order').order_by('-date')
    
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
    
    context = {
        'client': client,
        'orders': orders[:10],  # Limit to recent 10 orders for performance
        'payments': payments[:10],  # Limit to recent 10 payments
        'contacts': contacts,
        'addresses': addresses,
        'billing_data': billing_data,
        'billing_frequency': billing_frequency_info,
        'next_billing_date': next_billing_date,
        'stats': {
            'total_orders': total_orders,
            'total_spent': total_spent,
            'pending_orders': pending_orders,
            'completed_orders': completed_orders,
        }
    }
    
    return render(request, 'client_detail.html', context)