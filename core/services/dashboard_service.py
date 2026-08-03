from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Mapping
from urllib.parse import urlencode

from django.urls import reverse
from django.utils import timezone

from core.models import Employee


DATE_PRESET_CHOICES = (
    ('yesterday', 'Ayer'),
    ('last_week', 'Semana pasada'),
    ('last_month', 'Mes pasado'),
    ('custom', 'Personalizado'),
)


@dataclass(frozen=True)
class DashboardDateRange:
    start_date: date
    end_date: date
    preset: str
    label: str


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except ValueError:
        return None


def _previous_month_range(today: date) -> tuple[date, date]:
    first_day_this_month = today.replace(day=1)
    last_day_previous_month = first_day_this_month - timedelta(days=1)
    first_day_previous_month = last_day_previous_month.replace(day=1)
    return first_day_previous_month, last_day_previous_month


def get_dashboard_date_range(
    preset: str | None,
    *,
    custom_start: str | None = None,
    custom_end: str | None = None,
    today: date | None = None,
) -> DashboardDateRange:
    """Resolve dashboard date presets into an inclusive date range."""
    current_date = today or timezone.localdate()
    selected_preset = preset or 'yesterday'

    if selected_preset == 'custom':
        start_date = _parse_date(custom_start)
        end_date = _parse_date(custom_end)
        if start_date and end_date:
            if start_date > end_date:
                start_date, end_date = end_date, start_date
            return DashboardDateRange(
                start_date=start_date,
                end_date=end_date,
                preset='custom',
                label='Personalizado',
            )

    if selected_preset == 'last_week':
        current_week_start = current_date - timedelta(days=current_date.weekday())
        start_date = current_week_start - timedelta(days=7)
        end_date = current_week_start - timedelta(days=1)
        return DashboardDateRange(
            start_date=start_date,
            end_date=end_date,
            preset='last_week',
            label='Semana pasada',
        )

    if selected_preset == 'last_month':
        start_date, end_date = _previous_month_range(current_date)
        return DashboardDateRange(
            start_date=start_date,
            end_date=end_date,
            preset='last_month',
            label='Mes pasado',
        )

    yesterday = current_date - timedelta(days=1)
    return DashboardDateRange(
        start_date=yesterday,
        end_date=yesterday,
        preset='yesterday',
        label='Ayer',
    )


def get_employee_position(user: Any) -> str | None:
    """Return the linked employee position for an authenticated user, if any."""
    if not getattr(user, 'is_authenticated', False):
        return None

    try:
        employee = user.employee
    except (AttributeError, Employee.DoesNotExist):
        return None
    return employee.position


def get_current_week_pending_invoices_count(today: date | None = None) -> int:
    """Return pending billing clients for the current week, preserving home behavior."""
    from invoice import services as invoice_services

    current_date = today or timezone.localdate()
    week_start = current_date - timedelta(days=current_date.weekday())
    week_end = week_start + timedelta(days=6)
    return len(
        invoice_services.get_clients_needing_billing(
            start_date=week_start,
            end_date=week_end,
        )
    )


def _get_clients_with_debt_count() -> int:
    from clients.models import Client

    return Client.objects.filter(active=True, current_debt__gt=0).count()


def _get_driver_dashboard_actions(current_date: date) -> list[dict[str, Any]]:
    return [
        {
            'key': 'route',
            'title': 'Ruta del día',
            'description': 'Abrir la ruta programada para hoy e iniciar ventas.',
            'url': reverse('routes:today'),
            'icon': 'fa-route',
            'variant': 'primary',
            'badge_count': None,
            'meta': 'Programa de visitas del día',
        },
        {
            'key': 'outside_route_sales',
            'title': 'Ventas fuera de ruta',
            'description': 'Seleccionar un cliente para crear una venta manual.',
            'url': _url_with_query('clients:list', {'mode': 'outside_route_sales'}),
            'icon': 'fa-cart-plus',
            'variant': 'success',
            'badge_count': None,
            'meta': 'Búsqueda general de clientes',
        },
        {
            'key': 'clients',
            'title': 'Clientes',
            'description': 'Consultar clientes, ventas y pagos registrados.',
            'url': reverse('clients:list'),
            'icon': 'fa-users',
            'variant': 'secondary',
            'badge_count': None,
            'meta': 'Información y acciones por cliente',
        },
        {
            'key': 'day_report',
            'title': 'Reporte de hoy',
            'description': 'Revisar el corte de ventas y formas de pago del día.',
            'url': _url_with_query(
                'report:breakdown_payment_method',
                {'date': current_date.isoformat()},
            ),
            'icon': 'fa-clipboard-check',
            'variant': 'info',
            'badge_count': None,
            'meta': 'Resumen operativo del día',
        },
        {
            'key': 'credits',
            'title': 'Créditos',
            'description': 'Consultar clientes con deuda y registrar pagos.',
            'url': reverse('report:credit_report'),
            'icon': 'fa-credit-card',
            'variant': 'warning',
            'badge_count': _get_clients_with_debt_count(),
            'meta': 'Clientes con saldo pendiente',
        },
    ]


def _get_staff_dashboard_actions(current_date: date) -> list[dict[str, Any]]:
    return [
        {
            'key': 'sales',
            'title': 'Ventas',
            'description': 'Seleccionar un cliente para crear una venta.',
            'url': _url_with_query('clients:list', {'mode': 'outside_route_sales'}),
            'icon': 'fa-cart-plus',
            'variant': 'primary',
            'badge_count': None,
            'meta': 'La venta inicia desde el cliente',
        },
        {
            'key': 'clients',
            'title': 'Clientes',
            'description': 'Buscar clientes y revisar su resumen operativo.',
            'url': reverse('clients:list'),
            'icon': 'fa-users',
            'variant': 'secondary',
            'badge_count': None,
            'meta': 'Información, ventas y pagos',
        },
        {
            'key': 'routes',
            'title': 'Rutas',
            'description': 'Consultar rutas y clientes programados.',
            'url': reverse('routes:list'),
            'icon': 'fa-route',
            'variant': 'success',
            'badge_count': None,
            'meta': 'Agenda de entrega',
        },
        {
            'key': 'day_report',
            'title': 'Reporte de hoy',
            'description': 'Revisar ventas y pagos registrados en el día.',
            'url': _url_with_query(
                'report:breakdown_payment_method',
                {'date': current_date.isoformat()},
            ),
            'icon': 'fa-clipboard-check',
            'variant': 'info',
            'badge_count': None,
            'meta': 'Corte por forma de pago',
        },
        {
            'key': 'credits',
            'title': 'Créditos',
            'description': 'Consultar clientes con deuda y registrar pagos.',
            'url': reverse('report:credit_report'),
            'icon': 'fa-credit-card',
            'variant': 'warning',
            'badge_count': _get_clients_with_debt_count(),
            'meta': 'Clientes con saldo pendiente',
        },
        {
            'key': 'overdue_payments',
            'title': 'Pagos vencidos',
            'description': 'Revisar clientes con pagos atrasados.',
            'url': reverse('report:pending_payments'),
            'icon': 'fa-triangle-exclamation',
            'variant': 'danger',
            'badge_count': None,
            'meta': 'Seguimiento de cobranza',
        },
    ]


def get_delivery_dashboard_context(
    *,
    user: Any,
    today: date | None = None,
) -> dict[str, Any]:
    """Build the operational dashboard context for delivery and sales users."""
    current_date = today or timezone.localdate()
    # Staff navigation proposal is intentionally hidden until the dashboard
    # direction is approved.
    # if get_employee_position(user) == 'staff':
    #     dashboard_actions = _get_staff_dashboard_actions(current_date)
    dashboard_actions = _get_driver_dashboard_actions(current_date)
    return {
        'is_authenticated': True,
        'user': user,
        'today': current_date,
        'dashboard_title': 'Panel del repartidor',
        'dashboard_actions': dashboard_actions,
    }


def _get_overdue_clients_summary() -> dict[str, Decimal | int]:
    from clients.services.pending_payment_service import get_clients_with_pending_payments

    clients_data = get_clients_with_pending_payments()
    total_amount = sum(
        (item['total_overdue_amount'] for item in clients_data),
        Decimal('0.00'),
    )
    return {
        'count': len(clients_data),
        'total_amount': total_amount,
    }


def _get_pending_invoices_summary(start_date: date, end_date: date) -> dict[str, Decimal | int]:
    from invoice import services as invoice_services

    pending_clients = invoice_services.get_clients_needing_billing(
        start_date=start_date,
        end_date=end_date,
    )
    total_amount = sum(
        (item['total_amount'] for item in pending_clients),
        Decimal('0.00'),
    )
    total_orders = sum(item['orders_count'] for item in pending_clients)
    return {
        'count': len(pending_clients),
        'total_amount': total_amount,
        'total_orders': total_orders,
    }


def _url_with_query(url_name: str, query: Mapping[str, Any]) -> str:
    return f"{reverse(url_name)}?{urlencode(query)}"


def _get_dashboard_links(
    *,
    user: Any,
    selected_range: DashboardDateRange,
) -> dict[str, str]:
    links = {
        'overdue_clients': reverse('report:credit_report'),
        'orders_report': _url_with_query(
            'report:orders_report',
            {
                'date_filter': 'custom',
                'start_date': selected_range.start_date.isoformat(),
                'end_date': selected_range.end_date.isoformat(),
                'employee': 'all',
            },
        ),
        'routes_today': reverse('admin_routes') if user.is_staff else reverse('routes:list'),
        'invoices': '',
        'pending_invoices': '',
    }
    if user.is_staff:
        links['invoices'] = reverse('admin_invoices')
        links['pending_invoices'] = _url_with_query(
            'admin:billing_invoicefrequencyreport_changelist',
            {
                'date_preset': '',
                'start_date': selected_range.start_date.isoformat(),
                'end_date': selected_range.end_date.isoformat(),
            },
        )
    return links


def _get_manager_dashboard_actions(
    *,
    selected_range: DashboardDateRange,
    today: date,
) -> list[dict[str, Any]]:
    return [
        {
            'key': 'sales',
            'title': 'Ventas',
            'description': 'Revisar pedidos y registrar ventas.',
            'url': reverse('admin_orders'),
            'icon': 'fa-cart-shopping',
            'variant': 'primary',
            'meta': 'Panel de pedidos',
        },
        {
            'key': 'clients',
            'title': 'Clientes',
            'description': 'Buscar, crear y editar clientes.',
            'url': reverse('admin_clients'),
            'icon': 'fa-users',
            'variant': 'secondary',
            'meta': 'Resumen y datos del cliente',
        },
        {
            'key': 'invoices',
            'title': 'Facturas',
            'description': 'Administrar facturas emitidas y pendientes.',
            'url': reverse('admin_invoices'),
            'icon': 'fa-file-invoice-dollar',
            'variant': 'info',
            'meta': 'Facturación',
        },
        {
            'key': 'routes',
            'title': 'Rutas',
            'description': 'Configurar rutas y clientes asignados.',
            'url': reverse('admin_routes'),
            'icon': 'fa-route',
            'variant': 'success',
            'meta': 'Operación de entrega',
        },
        {
            'key': 'vehicles',
            'title': 'Vehículos',
            'description': 'Administrar vehículos y choferes asignados.',
            'url': reverse('admin:core_transport_changelist'),
            'icon': 'fa-truck',
            'variant': 'secondary',
            'meta': 'Django admin',
        },
        {
            'key': 'products',
            'title': 'Productos',
            'description': 'Administrar productos y precios.',
            'url': reverse('admin_products'),
            'icon': 'fa-box',
            'variant': 'secondary',
            'meta': 'Catálogo',
        },
        {
            'key': 'reports',
            'title': 'Reportes',
            'description': 'Consultar pedidos por rango de fechas.',
            'url': _url_with_query(
                'report:orders_report',
                {
                    'date_filter': 'custom',
                    'start_date': selected_range.start_date.isoformat(),
                    'end_date': selected_range.end_date.isoformat(),
                    'employee': 'all',
                },
            ),
            'icon': 'fa-chart-line',
            'variant': 'primary',
            'meta': 'Pedidos y ventas',
        },
        {
            'key': 'day_report',
            'title': 'Reporte de hoy',
            'description': 'Revisar el corte por método de pago.',
            'url': _url_with_query(
                'report:breakdown_payment_method',
                {'date': today.isoformat()},
            ),
            'icon': 'fa-clipboard-check',
            'variant': 'info',
            'meta': 'Corte diario',
        },
        {
            'key': 'credits',
            'title': 'Créditos',
            'description': 'Consultar reporte de crédito y cobranza.',
            'url': reverse('report:credit_report'),
            'icon': 'fa-credit-card',
            'variant': 'warning',
            'meta': 'Reporte de crédito',
        },
        {
            'key': 'overdue_payments',
            'title': 'Pagos vencidos',
            'description': 'Revisar clientes con pagos atrasados.',
            'url': reverse('report:pending_payments'),
            'icon': 'fa-triangle-exclamation',
            'variant': 'danger',
            'meta': 'Cobranza',
        },
    ]


def get_manager_dashboard_context(
    *,
    user: Any,
    params: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Build the full context for the manager backoffice dashboard."""
    params = params or {}
    selected_range = get_dashboard_date_range(
        params.get('date_preset') or 'yesterday',
        custom_start=params.get('start_date'),
        custom_end=params.get('end_date'),
    )

    from invoice import services as invoice_services
    from orders import services as order_services
    from routes import services as route_services

    today = timezone.localdate()
    return {
        'is_authenticated': True,
        'user': user,
        'date_options': DATE_PRESET_CHOICES,
        'date_range': selected_range,
        'selected_preset': selected_range.preset,
        'custom_start': selected_range.start_date.isoformat(),
        'custom_end': selected_range.end_date.isoformat(),
        'sales_snapshot': order_services.get_sales_snapshot(
            start_date=selected_range.start_date,
            end_date=selected_range.end_date,
        ),
        'overdue_clients': _get_overdue_clients_summary(),
        'invoice_balance': invoice_services.get_invoice_balance_snapshot(),
        'pending_invoices': _get_pending_invoices_summary(
            start_date=selected_range.start_date,
            end_date=selected_range.end_date,
        ),
        'route_clients_today': {
            'count': route_services.get_route_clients_due_count(today),
            'date': today,
        },
        # Manager navigation proposal is intentionally hidden in favor of the
        # dashboard snapshot until approved.
        # 'dashboard_actions': _get_manager_dashboard_actions(
        #     selected_range=selected_range,
        #     today=today,
        # ),
        'links': _get_dashboard_links(user=user, selected_range=selected_range),
    }
