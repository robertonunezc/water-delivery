from datetime import date
from typing import Optional, List
from django.db.models import QuerySet, Count, Sum, Q, Prefetch


def get_upcoming_route_orders(client, limit=10):
    """
    Get upcoming route client orders (specific deliveries) for a client.
    
    Args:
        client: Client instance
        limit: Maximum number of results to return (default: 10)
    
    Returns:
        QuerySet of upcoming RouteClientOrder instances
    """
    today = date.today()
    return client.client_route_orders.filter(
        visit_date__gte=today,
        is_completed=False
    ).select_related(
        'route__transportation__assigned_driver__user',
        'route',
        'order'
    ).order_by('visit_date')[:limit]


def get_recent_completed_route_orders(client, limit=5):
    """
    Get recent completed route orders for a client.

    Args:
        client: Client instance
        limit: Maximum number of results to return (default: 5)

    Returns:
        QuerySet of recently completed RouteClientOrder instances
    """
    return client.client_route_orders.filter(
        is_completed=True
    ).select_related(
        'route__transportation__assigned_driver__user',
        'route',
        'order'
    ).order_by('-completed_at')[:limit]


def get_clients_needing_billing(
    start_date: date,
    end_date: date,
    frequency_filter: Optional[str] = None,
    search_query: Optional[str] = None
) -> List[dict]:
    """
    Get clients that need billing within the specified date range.

    This function:
    1. Filters clients with active billing frequency
    2. Checks if they have orders in the period
    3. Determines if their billing date falls in the period
    4. Annotates with order statistics

    Args:
        start_date: Start of billing period
        end_date: End of billing period
        frequency_filter: Optional filter by frequency type
        search_query: Optional client name search

    Returns:
        List of dicts with client info and billing details
    """
    from .models import Client, ClientBillingFrecuency
    from orders.models import Order
    from core.utils import next_business_day

    # Base queryset: active clients with active billing frequency
    queryset = Client.objects.filter(
        active=True,
        client_billing_frecuency__is_active=True
    ).select_related(
        'client_billing_frecuency',
        'billing_data'
    ).prefetch_related(
        Prefetch(
            'orders',
            queryset=Order.objects.filter(
                order_date__date__gte=start_date,
                order_date__date__lte=end_date,
                status='COMPLETED'
            ).order_by('-order_date')
        )
    )
    print(queryset.count())
    print('Frecuency filter:', frequency_filter)
    # Apply frequency filter
    if frequency_filter:
        queryset = queryset.filter(client_billing_frecuency__frequency=frequency_filter)
    print('After frequency filter:', queryset.count())
    # Apply search filter
    if search_query:
        queryset = queryset.filter(
            Q(name__icontains=search_query) |
            Q(billing_data__razon_social__icontains=search_query) |
            Q(rfc__icontains=search_query)
        )
        print('After search filter:', queryset.count())
    # Annotate with order counts and amounts
    queryset = queryset.annotate(
        orders_in_period_count=Count(
            'orders',
            filter=Q(
                orders__order_date__date__gte=start_date,
                orders__order_date__date__lte=end_date,
                orders__status='COMPLETED'
            )
        ),
        total_amount_in_period=Sum(
            'orders__total_amount',
            filter=Q(
                orders__order_date__date__gte=start_date,
                orders__order_date__date__lte=end_date,
                orders__status='COMPLETED'
            )
        )
    )
    print('After annotation:', queryset.count())
    # Filter: only clients with orders
    queryset = queryset.filter(orders_in_period_count__gt=0)

    # Python-side filtering for date matching
    results = []

    for client in queryset:
        # Skip if client doesn't have billing frequency (shouldn't happen due to filter, but defensive)
        if not hasattr(client, 'billing_frecuency') or client.billing_frecuency is None:
            continue
        print(f'Processing client: {client.name}')   
        billing_freq = client.billing_frecuency

        # Special handling for contraentrega (when_delivery)
        if billing_freq.frequency == 'when_delivery':
            # For contraentrega, check if order_date + 1 business day falls in period
            for order in client.orders.all():
                billing_date = next_business_day(
                    order.order_date.date(),
                    skip_current=True
                )
                if start_date <= billing_date <= end_date:
                    results.append({
                        'client': client,
                        'billing_dates': [billing_date],
                        'orders_count': client.orders_in_period_count,
                        'total_amount': client.total_amount_in_period or 0,
                        'frequency_display': billing_freq.get_frequency_display(),
                        'billing_info': billing_freq.get_billing_info()
                    })
                    break  # Only add client once
        else:
            # For other frequencies, use the model's date matching logic
            if billing_freq.should_bill_in_period(start_date, end_date):
                billing_dates = billing_freq.get_billing_dates_in_period(start_date, end_date)
                results.append({
                    'client': client,
                    'billing_dates': billing_dates,
                    'orders_count': client.orders_in_period_count,
                    'total_amount': client.total_amount_in_period or 0,
                    'frequency_display': billing_freq.get_frequency_display(),
                    'billing_info': billing_freq.get_billing_info()
                })
    print('Final results count:', len(results))
    return results
