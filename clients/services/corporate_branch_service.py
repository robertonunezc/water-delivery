from calendar import monthrange
from datetime import date
from decimal import Decimal
from typing import Any, Mapping, Sequence
from urllib.parse import urlencode

from django.core.paginator import EmptyPage, Page, PageNotAnInteger, Paginator
from django.db.models import Count, DecimalField, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.urls import reverse
from django.utils import timezone

from clients.models import Client
from clients.services.client_service import get_upcoming_route_orders
from orders.models import Order, OrderStatus
from payment.models import Payment

ALLOWED_TABS = {'summary', 'orders', 'payments'}
DEFAULT_TAB = 'summary'
ZERO = Decimal('0.00')


def build_corporate_branch_workspace(
    corporate: Client,
    params: Mapping[str, str],
    *,
    today: date | None = None,
    orders_per_page: int = 15,
    payments_per_page: int = 15,
) -> dict[str, Any]:
    today = today or timezone.localdate()
    date_from, date_to = _resolve_date_range(params, today=today)
    active_tab = _resolve_active_tab(params.get('tab'))
    branches = list(
        corporate.branches.filter(type='branch').order_by('-active', 'name')
    )
    selected_branch = _resolve_selected_branch(branches, params.get('branch'))

    order_totals = _get_order_totals(branches, date_from=date_from, date_to=date_to)
    payment_totals = _get_payment_totals(branches, date_from=date_from, date_to=date_to)
    branch_rows = _build_branch_rows(
        branches=branches,
        selected_branch=selected_branch,
        order_totals=order_totals,
        payment_totals=payment_totals,
        date_from=date_from,
        date_to=date_to,
        active_tab=active_tab,
    )
    corporate_summary = _build_corporate_summary(branch_rows)

    selected_orders = Order.objects.none()
    selected_payments = Payment.objects.none()
    selected_branch_summary = _empty_selected_branch_summary()
    tab_urls = _build_empty_tab_urls()

    if selected_branch:
        selected_orders = _get_selected_orders(
            selected_branch,
            date_from=date_from,
            date_to=date_to,
        )
        selected_payments = _get_selected_payments(
            selected_branch,
            date_from=date_from,
            date_to=date_to,
        )
        selected_branch_summary = _build_selected_branch_summary(
            selected_branch=selected_branch,
            branch_rows=branch_rows,
            selected_orders=selected_orders,
        )
        tab_urls = _build_tab_urls(
            selected_branch=selected_branch,
            date_from=date_from,
            date_to=date_to,
        )

    return {
        'corporate': corporate,
        'date_from': date_from,
        'date_to': date_to,
        'date_from_value': date_from.isoformat(),
        'date_to_value': date_to.isoformat(),
        'active_tab': active_tab,
        'branches': branch_rows,
        'selected_branch': selected_branch,
        'corporate_summary': corporate_summary,
        'selected_branch_summary': selected_branch_summary,
        'orders_page': _paginate(
            selected_orders,
            params.get('orders_page'),
            per_page=orders_per_page,
        ),
        'payments_page': _paginate(
            selected_payments,
            params.get('payments_page'),
            per_page=payments_per_page,
        ),
        'tab_urls': tab_urls,
        'orders_page_url_prefix': _page_url_prefix(
            selected_branch=selected_branch,
            date_from=date_from,
            date_to=date_to,
            tab='orders',
            page_param='orders_page',
        ),
        'payments_page_url_prefix': _page_url_prefix(
            selected_branch=selected_branch,
            date_from=date_from,
            date_to=date_to,
            tab='payments',
            page_param='payments_page',
        ),
    }


def _resolve_date_range(
    params: Mapping[str, str],
    *,
    today: date,
) -> tuple[date, date]:
    fallback = _current_month_range(today)
    raw_date_from = params.get('date_from')
    raw_date_to = params.get('date_to')

    if not raw_date_from or not raw_date_to:
        return fallback

    try:
        date_from = date.fromisoformat(raw_date_from)
        date_to = date.fromisoformat(raw_date_to)
    except ValueError:
        return fallback

    if date_from > date_to:
        return fallback

    return date_from, date_to


def _current_month_range(today: date) -> tuple[date, date]:
    last_day = monthrange(today.year, today.month)[1]
    return date(today.year, today.month, 1), date(today.year, today.month, last_day)


def _resolve_active_tab(raw_tab: str | None) -> str:
    if raw_tab in ALLOWED_TABS:
        return raw_tab
    return DEFAULT_TAB


def _resolve_selected_branch(
    branches: Sequence[Client],
    raw_branch_id: str | None,
) -> Client | None:
    if raw_branch_id:
        try:
            branch_id = int(raw_branch_id)
        except (TypeError, ValueError):
            branch_id = None

        for branch in branches:
            if branch.pk == branch_id:
                return branch

    return branches[0] if branches else None


def _get_order_totals(
    branches: Sequence[Client],
    *,
    date_from: date,
    date_to: date,
) -> dict[int, dict[str, Any]]:
    if not branches:
        return {}

    amount_field = DecimalField(max_digits=12, decimal_places=2)
    rows = (
        Order.objects.filter(
            client__in=branches,
            order_date__date__gte=date_from,
            order_date__date__lte=date_to,
        )
        .values('client_id')
        .annotate(
            order_count=Count('id'),
            sales_total=Coalesce(
                Sum(
                    'total_amount',
                    filter=~Q(status=OrderStatus.CANCELLED.value),
                ),
                Value(ZERO, output_field=amount_field),
            ),
            cancelled_order_count=Count(
                'id',
                filter=Q(status=OrderStatus.CANCELLED.value),
            ),
            cancelled_order_amount=Coalesce(
                Sum(
                    'total_amount',
                    filter=Q(status=OrderStatus.CANCELLED.value),
                ),
                Value(ZERO, output_field=amount_field),
            ),
        )
    )
    return {row['client_id']: row for row in rows}


def _get_payment_totals(
    branches: Sequence[Client],
    *,
    date_from: date,
    date_to: date,
) -> dict[int, Decimal]:
    if not branches:
        return {}

    amount_field = DecimalField(max_digits=12, decimal_places=2)
    rows = (
        Payment.objects.filter(
            client__in=branches,
            status='completed',
            date__date__gte=date_from,
            date__date__lte=date_to,
        )
        .exclude(method='pending_credit')
        .values('client_id')
        .annotate(
            payment_total=Coalesce(
                Sum('amount'),
                Value(ZERO, output_field=amount_field),
            ),
        )
    )
    return {row['client_id']: row['payment_total'] for row in rows}


def _build_branch_rows(
    *,
    branches: Sequence[Client],
    selected_branch: Client | None,
    order_totals: dict[int, dict[str, Any]],
    payment_totals: dict[int, Decimal],
    date_from: date,
    date_to: date,
    active_tab: str,
) -> list[dict[str, Any]]:
    rows = []
    for branch in branches:
        order_data = order_totals.get(branch.pk, {})
        is_selected = bool(selected_branch and branch.pk == selected_branch.pk)
        rows.append(
            {
                'branch': branch,
                'order_count': order_data.get('order_count', 0),
                'sales_total': order_data.get('sales_total', ZERO),
                'payment_total': payment_totals.get(branch.pk, ZERO),
                'current_debt': branch.current_debt or ZERO,
                'cancelled_order_count': order_data.get('cancelled_order_count', 0),
                'cancelled_order_amount': order_data.get('cancelled_order_amount', ZERO),
                'is_selected': is_selected,
                'url': _workspace_url(
                    branch=branch,
                    tab=active_tab,
                    date_from=date_from,
                    date_to=date_to,
                ),
            }
        )
    return rows


def _build_corporate_summary(branch_rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    return {
        'total_orders': sum(row['order_count'] for row in branch_rows),
        'total_sales': sum((row['sales_total'] for row in branch_rows), ZERO),
        'total_payments': sum((row['payment_total'] for row in branch_rows), ZERO),
        'total_current_debt': sum(
            (row['current_debt'] for row in branch_rows),
            ZERO,
        ),
    }


def _get_selected_orders(
    selected_branch: Client,
    *,
    date_from: date,
    date_to: date,
) -> Any:
    return (
        Order.objects.filter(
            client=selected_branch,
            order_date__date__gte=date_from,
            order_date__date__lte=date_to,
        )
        .prefetch_related('items__product', 'payments')
        .order_by('-order_date', '-id')
    )


def _get_selected_payments(
    selected_branch: Client,
    *,
    date_from: date,
    date_to: date,
) -> Any:
    return (
        Payment.objects.filter(
            client=selected_branch,
            status='completed',
            date__date__gte=date_from,
            date__date__lte=date_to,
        )
        .exclude(method='pending_credit')
        .select_related('order', 'created_by')
        .order_by('-date', '-id')
    )


def _build_selected_branch_summary(
    *,
    selected_branch: Client,
    branch_rows: Sequence[dict[str, Any]],
    selected_orders: Any,
) -> dict[str, Any]:
    selected_row = next(
        row for row in branch_rows if row['branch'].pk == selected_branch.pk
    )
    last_order = selected_orders.first()
    upcoming_route_orders = list(get_upcoming_route_orders(selected_branch, limit=1))
    next_route_order = upcoming_route_orders[0] if upcoming_route_orders else None

    return {
        **selected_row,
        'last_order_date': last_order.order_date if last_order else None,
        'next_route_order': next_route_order,
        'detail_url': reverse('clients:detail', args=[selected_branch.pk]),
    }


def _empty_selected_branch_summary() -> dict[str, Any]:
    return {
        'branch': None,
        'order_count': 0,
        'sales_total': ZERO,
        'payment_total': ZERO,
        'current_debt': ZERO,
        'cancelled_order_count': 0,
        'cancelled_order_amount': ZERO,
        'is_selected': False,
        'url': '',
        'last_order_date': None,
        'next_route_order': None,
        'detail_url': '',
    }


def _build_tab_urls(
    *,
    selected_branch: Client,
    date_from: date,
    date_to: date,
) -> dict[str, str]:
    return {
        tab: _workspace_url(
            branch=selected_branch,
            tab=tab,
            date_from=date_from,
            date_to=date_to,
        )
        for tab in sorted(ALLOWED_TABS)
    }


def _build_empty_tab_urls() -> dict[str, str]:
    return {tab: '#' for tab in sorted(ALLOWED_TABS)}


def _workspace_url(
    *,
    branch: Client,
    tab: str,
    date_from: date,
    date_to: date,
) -> str:
    query = urlencode(
        {
            'branch': branch.pk,
            'tab': tab,
            'date_from': date_from.isoformat(),
            'date_to': date_to.isoformat(),
        }
    )
    return f"?{query}"


def _page_url_prefix(
    *,
    selected_branch: Client | None,
    date_from: date,
    date_to: date,
    tab: str,
    page_param: str,
) -> str:
    if not selected_branch:
        return '#'

    query = urlencode(
        {
            'branch': selected_branch.pk,
            'tab': tab,
            'date_from': date_from.isoformat(),
            'date_to': date_to.isoformat(),
        }
    )
    return f"?{query}&{page_param}="


def _paginate(items: Any, page_number: str | None, *, per_page: int) -> Page:
    paginator = Paginator(items, per_page)
    try:
        return paginator.page(page_number or 1)
    except (EmptyPage, PageNotAnInteger):
        return paginator.page(1)
