from dataclasses import dataclass
from datetime import date, timedelta

from django.db.models import QuerySet

from .models import Route, RouteClient, RouteClientOrder


@dataclass(frozen=True)
class RouteDetailPayload:
    route_clients: QuerySet[RouteClient]
    recent_orders: QuerySet[RouteClientOrder]
    search_query: str
    today: date
    is_today_view: bool = False


def get_route_detail_payload(route: Route, search_query: str) -> RouteDetailPayload:
    route_clients = (
        RouteClient.objects.for_route(route)
        .search_by_client(search_query)
        .with_client_details()
        .with_client_products()
        .with_recent_client_orders()
        .ordered_for_detail()
    )

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
