from django.shortcuts import render, get_object_or_404
from django.db.models import Sum, Count
from .models import Client

def list(request):
    clients = Client.objects.all()
    return render(request, 'list_clients.html', {'clients': clients})

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