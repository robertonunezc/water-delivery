from django.shortcuts import render, get_object_or_404
from django.db.models import Sum, Count, Q
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from .models import Client

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
    
    context = {
        'client': client,
        'orders': orders[:10],  # Limit to recent 10 orders for performance
        'payments': payments[:10],  # Limit to recent 10 payments
        'contacts': contacts,
        'addresses': addresses,
        'billing_data': billing_data,
        'stats': {
            'total_orders': total_orders,
            'total_spent': total_spent,
            'pending_orders': pending_orders,
            'completed_orders': completed_orders,
        }
    }
    
    return render(request, 'client_detail.html', context)