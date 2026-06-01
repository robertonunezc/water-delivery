from datetime import timedelta
from decimal import Decimal
from typing import List, Dict, Any
from django.utils import timezone
from django.db.models import Max
from clients.models import Client, CreditTransaction
from orders.models import Order

def get_overdue_orders_for_client(client: Client) -> Dict[str, Any]:
    """
    Get overdue orders for a specific client based on their credit configuration.
    Returns a dict with:
    - total_overdue_amount: Decimal
    - days_overdue: int (max days overdue among orders)
    - overdue_orders: List[Order]
    """
    result = {
        'total_overdue_amount': Decimal('0.00'),
        'days_overdue': 0,
        'overdue_orders': []
    }
    
    if not hasattr(client, 'credit_config') or client.credit_config is None:
        return result
        
    max_payment_days = client.credit_config.max_payment_days
    current_date = timezone.now().date()
    
    unpaid_orders = Order.objects.unpaid().filter(client=client).select_related('client').prefetch_related('invoice_links__invoice')
    
    overdue_orders = []
    max_days = 0
    total_overdue = Decimal('0.00')
    
    requires_billing = client.requires_billing
    
    for order in unpaid_orders:
        is_overdue = False
        days_overdue = 0
        
        total_amount = order.total_amount
        total_paid = getattr(order, 'total_paid', Decimal('0.00'))
        remaining_amount = total_amount - total_paid
        
        if requires_billing:
            invoice_links = order.invoice_links.all()
            for link in invoice_links:
                if link.invoice and link.invoice.emmited_at:
                    days_since_emission = (current_date - link.invoice.emmited_at).days
                    if days_since_emission > max_payment_days:
                        is_overdue = True
                        days_overdue = max(days_overdue, days_since_emission - max_payment_days)
        else:
            days_since_creation = (current_date - order.order_date.date()).days
            if days_since_creation > max_payment_days:
                is_overdue = True
                days_overdue = max(days_overdue, days_since_creation - max_payment_days)
                
        if is_overdue:
            order.days_overdue = days_overdue
            order.remaining_amount = remaining_amount
            overdue_orders.append(order)
            total_overdue += remaining_amount
            if days_overdue > max_days:
                max_days = days_overdue
                
    overdue_orders.sort(key=lambda x: x.days_overdue, reverse=True)
    
    result['total_overdue_amount'] = total_overdue
    result['days_overdue'] = max_days
    result['overdue_orders'] = overdue_orders
    
    return result

def get_clients_with_pending_payments() -> List[Dict[str, Any]]:
    """
    Get all clients that have pending payments (overdue orders).
    """
    clients = Client.objects.filter(active=True, credit_config__isnull=False).select_related('credit_config')
    clients_map = {client.id: client for client in clients}
    
    unpaid_orders = Order.objects.unpaid().filter(
        client_id__in=clients_map.keys()
    ).select_related('client', 'client__credit_config').prefetch_related('invoice_links__invoice')
    
    orders_by_client = {}
    for order in unpaid_orders:
        if order.client_id not in orders_by_client:
            orders_by_client[order.client_id] = []
        orders_by_client[order.client_id].append(order)
        
    current_date = timezone.now().date()
    clients_data = []
    
    last_payments = CreditTransaction.objects.filter(
        client_id__in=clients_map.keys(),
        transaction_type='payment'
    ).values('client_id').annotate(last_date=Max('created_at'))
    
    last_payment_map = {item['client_id']: item['last_date'] for item in last_payments}

    for client_id, orders in orders_by_client.items():
        client = clients_map[client_id]
        max_payment_days = client.credit_config.max_payment_days
        requires_billing = client.requires_billing
        
        overdue_orders = []
        max_days = 0
        total_overdue = Decimal('0.00')
        
        for order in orders:
            is_overdue = False
            days_overdue = 0
            
            total_amount = order.total_amount
            total_paid = getattr(order, 'total_paid', Decimal('0.00'))
            remaining_amount = total_amount - total_paid
            
            if requires_billing:
                invoice_links = order.invoice_links.all()
                for link in invoice_links:
                    if link.invoice and link.invoice.emmited_at:
                        days_since_emission = (current_date - link.invoice.emmited_at).days
                        if days_since_emission > max_payment_days:
                            is_overdue = True
                            days_overdue = max(days_overdue, days_since_emission - max_payment_days)
            else:
                days_since_creation = (current_date - order.order_date.date()).days
                if days_since_creation > max_payment_days:
                    is_overdue = True
                    days_overdue = max(days_overdue, days_since_creation - max_payment_days)
                    
            if is_overdue:
                order.days_overdue = days_overdue
                order.remaining_amount = remaining_amount
                overdue_orders.append(order)
                total_overdue += remaining_amount
                if days_overdue > max_days:
                    max_days = days_overdue
                    
        if overdue_orders:
            overdue_orders.sort(key=lambda x: x.days_overdue, reverse=True)
            clients_data.append({
                'client': client,
                'total_overdue_amount': total_overdue,
                'days_overdue': max_days,
                'missing_payment_orders': overdue_orders,
                'last_payment_date': last_payment_map.get(client_id)
            })
            
    clients_data.sort(key=lambda x: x['total_overdue_amount'], reverse=True)
    return clients_data
