from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Iterable
from urllib.parse import urlencode

from django.db.models import Count, Prefetch, Q, QuerySet, Sum
from django.urls import reverse
from django.utils import timezone

from clients.models import Client
from core.models import Employee, Transport
from orders.models import Order, OrderProduct, OrderStatus
from .models import (
    Route,
    RouteClient,
    RouteClientOrder,
    TruckInventoryLine,
    TruckInventorySession,
)
from route_confirmations.services import attach_confirmation_states


@dataclass(frozen=True)
class RouteDetailPayload:
    route_clients: list[RouteClient]
    recent_orders: QuerySet[RouteClientOrder]
    search_query: str
    today: date
    is_today_view: bool = False


def get_route_detail_payload(
    route: Route,
    search_query: str,
    user: Any | None = None,
) -> RouteDetailPayload:
    route_clients_queryset = (
        RouteClient.objects.for_route(route)
        .search_by_client(search_query)
        .with_client_details()
        .with_client_products()
        .with_recent_client_orders()
        .ordered_for_detail()
    )
    if user is not None:
        route_clients_queryset = with_active_reminder_counts(
            route_clients_queryset,
            user=user,
        )
    route_clients = attach_confirmation_states(list(route_clients_queryset))

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


def get_driver_transportation(user: Any) -> Transport | None:
    """Return the active truck assigned to the user's employee profile."""
    try:
        employee = user.employee
    except Employee.DoesNotExist:
        return None

    return Transport.objects.filter(
        assigned_driver=employee,
        is_active=True,
    ).first()


def get_inventory_routes_for_user(
    user: Any,
    service_date: date,
) -> QuerySet[Route]:
    """Return active inventory routes the user can work with on the date."""
    weekday = service_date.strftime('%A').lower()
    routes = (
        Route.objects.filter(is_active=True, weekday=weekday)
        .select_related('transportation')
        .order_by('name', 'id')
    )
    if getattr(user, 'is_staff', False):
        return routes

    transportation = get_driver_transportation(user)
    if transportation is None:
        return routes.none()
    return routes.filter(transportation=transportation)


def get_or_create_inventory_session(
    route: Route,
    transportation: Transport,
    service_date: date,
    user: Any | None = None,
) -> TruckInventorySession:
    """Get or create the route/truck inventory session for the service date."""
    if route.transportation_id != transportation.pk:
        raise ValueError('La ruta no corresponde a la camioneta seleccionada.')

    session, _created = TruckInventorySession.objects.get_or_create(
        route=route,
        transportation=transportation,
        service_date=service_date,
        defaults={'opened_by': user},
    )
    return session


def get_inventory_sessions_for_user(user: Any) -> QuerySet[TruckInventorySession]:
    """Return truck inventory sessions visible to the user."""
    sessions = (
        TruckInventorySession.objects.select_related(
            'route',
            'transportation',
            'opened_by',
            'closed_by',
        )
        .prefetch_related(
            Prefetch(
                'lines',
                queryset=TruckInventoryLine.objects.select_related('product'),
                to_attr='active_lines',
            )
        )
        .order_by(
            '-service_date',
            'route__name',
            'transportation__license_plate',
            '-id',
        )
    )
    if getattr(user, 'is_staff', False):
        return sessions

    transportation = get_driver_transportation(user)
    if transportation is None:
        return sessions.none()
    return sessions.filter(transportation=transportation)


def build_inventory_session_rows(
    sessions: Iterable[TruckInventorySession],
) -> list[dict[str, Any]]:
    """Build table rows with persisted reconciliation totals."""
    rows: list[dict[str, Any]] = []
    for session in sessions:
        lines = getattr(session, 'active_lines', None)
        if lines is None:
            lines = list(session.lines.filter(deleted_at__isnull=True))
        totals = _build_inventory_totals(list(lines))
        has_differences = (
            totals['sales_difference'] != 0
            or totals['missing_containers'] != 0
        )
        query = urlencode({
            'mode': 'form',
            'date': session.service_date.isoformat(),
            'route': session.route_id,
            'transportation': session.transportation_id,
        })
        rows.append({
            'session': session,
            'totals': totals,
            'has_differences': has_differences,
            'url': f"{reverse('routes:truck_inventory')}?{query}",
        })
    return rows


def get_reported_sales_by_product(
    route: Route,
    transportation: Transport,
    service_date: date,
) -> dict[int, int]:
    """Aggregate completed reported sales for a route/truck service day."""
    linked_order_ids = _get_route_client_order_ids(route, service_date)
    due_client_order_ids = _get_due_route_client_order_ids(route, service_date)
    driver_order_ids = _get_driver_outside_route_order_ids(
        transportation,
        service_date,
    )

    order_ids = linked_order_ids | due_client_order_ids | driver_order_ids
    if not order_ids:
        return {}

    rows = (
        OrderProduct.objects.filter(order_id__in=order_ids)
        .values('product_id')
        .annotate(total_quantity=Sum('quantity'))
    )
    return {
        row['product_id']: row['total_quantity'] or 0
        for row in rows
    }


def _get_route_client_order_ids(route: Route, service_date: date) -> set[int]:
    return set(
        RouteClientOrder.objects.filter(
            route=route,
            visit_date=service_date,
            order__status=OrderStatus.COMPLETED.value,
            order__order_date__date=service_date,
        ).values_list('order_id', flat=True)
    )


def _get_due_route_client_order_ids(route: Route, service_date: date) -> set[int]:
    due_client_ids = RouteClient.objects.due_on(service_date).filter(
        route=route,
    ).values_list('client_id', flat=True)

    return set(
        Order.objects.filter(
            client_id__in=due_client_ids,
            status=OrderStatus.COMPLETED.value,
            order_date__date=service_date,
        )
        .filter(Q(route_orders__isnull=True) | Q(route_orders__route=route))
        .values_list('pk', flat=True)
        .distinct()
    )


def _get_driver_outside_route_order_ids(
    transportation: Transport,
    service_date: date,
) -> set[int]:
    driver_order_ids: set[int] = set()
    driver = transportation.assigned_driver
    if driver is not None and driver.user_id:
        driver_order_ids = set(
            Order.objects.filter(
                owner_id=driver.user_id,
                status=OrderStatus.COMPLETED.value,
                order_date__date=service_date,
                route_orders__isnull=True,
            ).values_list('pk', flat=True)
        )
    return driver_order_ids


def sync_session_reported_sales(session: TruckInventorySession) -> None:
    """Refresh reported sales and stored calculations for every session line."""
    reported_sales = get_reported_sales_by_product(
        session.route,
        session.transportation,
        session.service_date,
    )
    lines = TruckInventoryLine.objects.filter(
        session=session,
        deleted_at__isnull=True,
    )
    for line in lines:
        line.reported_sales = reported_sales.get(line.product_id, 0)
        line.recalculate()
        line.save(
            update_fields=[
                'reported_sales',
                'expected_sales',
                'sales_difference',
                'missing_containers',
                'updated_at',
            ]
        )

    existing_product_ids = set(lines.values_list('product_id', flat=True))
    missing_product_ids = set(reported_sales) - existing_product_ids
    for product_id in missing_product_ids:
        line = TruckInventoryLine(
            session=session,
            product_id=product_id,
            reported_sales=reported_sales[product_id],
        )
        line.recalculate()
        line.save()


def sync_open_inventory_sessions_for_order(order: Order) -> int:
    """Refresh open truck inventory sessions affected by a completed order."""
    order_state = (
        Order.objects.filter(pk=order.pk)
        .values('status', 'order_date', 'owner_id', 'client_id')
        .first()
    )
    if order_state is None or order_state['status'] != OrderStatus.COMPLETED.value:
        return 0

    service_date = timezone.localdate(order_state['order_date'])
    session_filter = Q(
        route__route_client_orders__order_id=order.pk,
        route__route_client_orders__visit_date=service_date,
    )
    owner_id = order_state['owner_id']
    if owner_id:
        session_filter |= Q(
            transportation__assigned_driver__user_id=owner_id,
        )
    client_id = order_state['client_id']
    has_route_order = RouteClientOrder.objects.filter(order_id=order.pk).exists()
    if client_id and not has_route_order:
        due_route_ids = RouteClient.objects.due_on(service_date).filter(
            client_id=client_id,
        ).values_list('route_id', flat=True)
        session_filter |= Q(route_id__in=due_route_ids)

    sessions = list(
        TruckInventorySession.objects.filter(
            service_date=service_date,
            status=TruckInventorySession.Status.OPEN,
        )
        .filter(session_filter)
        .select_related('route', 'transportation')
        .distinct()
    )
    for session in sessions:
        sync_session_reported_sales(session)
    return len(sessions)


def get_daily_inventory_summaries(selected_date: date) -> list[dict[str, Any]]:
    """Return truck inventory reconciliation summaries for the daily report."""
    sessions = (
        TruckInventorySession.objects.filter(service_date=selected_date)
        .select_related('route', 'transportation')
        .prefetch_related('lines__product')
        .order_by('route__name', 'transportation__license_plate', 'id')
    )
    summaries: list[dict[str, Any]] = []
    for session in sessions:
        lines = [
            line
            for line in session.lines.all()
            if line.deleted_at is None
        ]
        totals = _build_inventory_totals(lines)
        summaries.append({
            'session': session,
            'route': session.route,
            'transportation': session.transportation,
            'status': session.status,
            'totals': totals,
            'lines': lines,
            'has_differences': (
                totals['sales_difference'] != 0
                or totals['missing_containers'] != 0
            ),
        })
    return summaries


def get_route_inventory_status(route: Route, service_date: date) -> dict[str, Any]:
    """Return compact inventory status for a route/date header."""
    session = (
        TruckInventorySession.objects.filter(
            route=route,
            service_date=service_date,
        )
        .prefetch_related('lines')
        .order_by('-created_at', '-id')
        .first()
    )
    status = 'Sin captura'
    has_differences = False
    if session is not None:
        totals = _build_inventory_totals([
            line for line in session.lines.all() if line.deleted_at is None
        ])
        has_differences = (
            totals['sales_difference'] != 0
            or totals['missing_containers'] != 0
        )
        status = 'Con diferencias' if has_differences else session.status

    query_data: dict[str, Any] = {
        'mode': 'form',
        'date': service_date.isoformat(),
    }
    if route.transportation_id:
        query_data.update({
            'route': route.pk,
            'transportation': route.transportation_id,
        })

    return {
        'session': session,
        'status': status,
        'url': f"{reverse('routes:truck_inventory')}?{urlencode(query_data)}",
        'has_differences': has_differences,
    }


def _build_inventory_totals(lines: list[TruckInventoryLine]) -> dict[str, int]:
    return {
        'full_loaded': sum(line.full_loaded for line in lines),
        'full_returned': sum(line.full_returned for line in lines),
        'empty_returned': sum(line.empty_returned for line in lines),
        'expected_sales': sum(line.expected_sales for line in lines),
        'reported_sales': sum(line.reported_sales for line in lines),
        'sales_difference': sum(line.sales_difference for line in lines),
        'missing_containers': sum(line.missing_containers for line in lines),
    }
