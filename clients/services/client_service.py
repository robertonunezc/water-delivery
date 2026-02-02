from datetime import date


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