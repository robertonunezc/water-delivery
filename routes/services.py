from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from django.db.models import Count, Q, QuerySet
from django.utils import timezone

from clients.models import Client
from .models import Route, RouteClient, RouteClientOrder


@dataclass(frozen=True)
class RouteDetailPayload:
    route_clients: QuerySet[RouteClient]
    recent_orders: QuerySet[RouteClientOrder]
    search_query: str
    today: date
    is_today_view: bool = False


def get_route_detail_payload(
    route: Route,
    search_query: str,
    user: Any | None = None,
) -> RouteDetailPayload:
    route_clients = (
        RouteClient.objects.for_route(route)
        .search_by_client(search_query)
        .with_client_details()
        .with_client_products()
        .with_recent_client_orders()
        .ordered_for_detail()
    )
    if user is not None:
        route_clients = with_active_reminder_counts(route_clients, user=user)

    recent_orders = (
        RouteClientOrder.objects.filter(
            route=route,
            visit_date__gte=date.today() - timedelta(days=7),
        )
        .select_related('client', 'order')
        .order_by('-visit_date', 'sequence')
    )

    return RouteDetailPayload(
        route_clients=route_clients,
        recent_orders=recent_orders,
        search_query=search_query,
        today=date.today(),
    )


def with_active_reminder_counts(
    route_clients: QuerySet[RouteClient],
    *,
    user: Any,
    today: date | None = None,
) -> QuerySet[RouteClient]:
    """Annotate route clients with the user's active, non-overdue reminder count."""
    current_date = today or timezone.localdate()
    active_reminder_filter = (
        Q(client__reminders__created_by=user)
        & Q(client__reminders__completed_at__isnull=True)
        & Q(client__reminders__deleted_at__isnull=True)
        & (
            Q(client__reminders__reminder_date__isnull=True)
            | Q(client__reminders__reminder_date__gte=current_date)
        )
    )
    return route_clients.annotate(
        active_reminders_count=Count(
            'client__reminders',
            filter=active_reminder_filter,
            distinct=True,
        )
    )


def get_route_clients_due_count(target_date: date) -> int:
    """Return the number of active route clients due on the given date."""
    return RouteClient.objects.due_on(target_date).count()


def get_current_route_for_client(
    client: Client,
    target_date: date | None = None,
) -> Route | None:
    """Return the client's active route assignment due on the target date."""
    current_date = target_date or timezone.localdate()
    route_client = (
        RouteClient.objects.due_on(current_date)
        .filter(client=client, route__is_active=True)
        .select_related('route')
        .order_by('sequence', 'route_id', 'id')
        .first()
    )
    if route_client is None:
        return None
    return route_client.route
