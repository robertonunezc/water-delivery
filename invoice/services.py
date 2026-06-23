"""
Billing service layer.

Contains business logic for billing operations including:
- Finding clients that need billing in a period
- Updating billing dates for clients
- Validating billing orders
- Date range utilities
"""
from datetime import date, timedelta, datetime
from typing import Optional, List, Dict, Tuple
from decimal import Decimal
from django.db.models import Count, Sum, Q, Prefetch
from django.core.exceptions import ValidationError
from calendar import monthrange

from invoice.models import InvoiceSchedule
from clients.models import Client, InvoiceData
from core.utils import get_first_last_day_of_month
from orders.models import Order


def _get_invoice_billing_owner(client: Client) -> Client:
    """Return the client whose fiscal data must be used for invoice generation."""
    if client.type == 'branch' and not client.billing_override_enabled:
        if client.corporate_id is None:
            raise ValidationError(
                f'El cliente "{client.name}" no puede facturarse sin un cliente corporativo asociado.'
            )
        return client.corporate
    return client


def _get_missing_invoice_data_fields(invoice_data: Optional[InvoiceData]) -> List[str]:
    """Return required invoice data fields that are missing or blank."""
    if invoice_data is None:
        return ['RFC', 'Razón social']

    missing_fields: List[str] = []
    if not (invoice_data.rfc or '').strip():
        missing_fields.append('RFC')
    if not (invoice_data.razon_social or '').strip():
        missing_fields.append('Razón social')
    return missing_fields


def validate_client_invoice_generation_requirements(client: Client) -> None:
    """Validate the fiscal requirements needed to generate an invoice for a client."""
    billing_owner = _get_invoice_billing_owner(client)
    missing_messages: List[str] = []
    invoice_data = billing_owner.invoice_data if hasattr(billing_owner, 'invoice_data') else None

    missing_invoice_fields = _get_missing_invoice_data_fields(invoice_data)
    if missing_invoice_fields:
        missing_messages.append(
            f"faltan datos de facturación requeridos ({', '.join(missing_invoice_fields)})"
        )

    has_billing_address = billing_owner.addresses.filter(
        type='billing',
        active=True,
    ).exists()
    if not has_billing_address:
        missing_messages.append('falta un domicilio de tipo fiscal activo')

    if not missing_messages:
        return

    owner_label = 'el mismo cliente'
    if billing_owner.pk != client.pk:
        owner_label = f'el cliente corporativo "{billing_owner.name}"'

    raise ValidationError(
        f'El cliente "{client.name}" no puede facturarse porque '
        f"{' y '.join(missing_messages)} en {owner_label}."
    )


def get_clients_with_invoices() -> 'django.db.models.QuerySet':
    """
    Return a queryset of active clients that have at least one invoice.

    Used for filter dropdowns in the invoice admin list view.

    Returns:
        QuerySet[Client]: Ordered by name, distinct, pre-filtered to clients
        that have been invoiced at least once.
    """
    return (
        Client.objects
        .filter(invoices__isnull=False)
        .distinct()
        .order_by('name')
    )



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
    from core.utils import next_business_day

    # Base queryset: active clients with active billing frequency
    queryset = Client.objects.filter(
        active=True,
        requires_billing=True,
        invoice_schedule__is_active=True
    ).select_related(
        'invoice_schedule',
        'invoice_data'
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

    # Apply frequency filter
    if frequency_filter:
        queryset = queryset.filter(invoice_schedule__frequency=frequency_filter)
    # Apply search filter
    if search_query:
        queryset = queryset.filter(
            Q(name__icontains=search_query) |
            Q(invoice_data__razon_social__icontains=search_query) |
            Q(rfc__icontains=search_query)
        )
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
    # Don't filter by orders - show all clients whose billing date falls in the period
    # They may have unbilled orders from previous periods or need billing preparation

    # Python-side filtering for date matching
    results = []

    for client in queryset:
        # Skip if client doesn't have billing frequency (shouldn't happen due to filter, but defensive)
        if not hasattr(client, 'invoice_schedule') or client.invoice_schedule is None:
            continue
        billing_freq = client.invoice_schedule

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


def set_billing_date_to_clients() -> Optional[date]:
    """
    Update next_billing_date for all active clients with active billing frequency.

    This triggers the save logic on InvoiceSchedule which calculates
    the next billing date based on the frequency configuration.
    """
    first_day, last_day = get_first_last_day_of_month(date.today().year, date.today().month)
    queryset = Client.objects.filter(
        active=True,
        requires_billing=True,
        invoice_schedule__is_active=True
    ).select_related(
        'invoice_schedule',
        'invoice_data'
    )
    print('Total clients to update:', queryset.count())
    for client in queryset:
        client.invoice_schedule.save()  # Triggers save logic to update next_billing_date
    print('Billing dates updated successfully')
    return queryset


# Billing Order Validation Services


def add_order_to_invoice(
    invoice: 'invoice.models.Invoice',
    order: Order,
    exclude_invoice_order_link_id: Optional[int] = None,
) -> 'invoice.models.InvoiceOrderLink':
    """
    Add an order to an invoice with business rule validation.

    This is the single source of truth for adding orders to invoices.
    Validates that total won't exceed invoice amount (when auto_amount=False).

    Args:
        invoice: Invoice instance (must have PK)
        order: Order instance to add
        exclude_invoice_order_link_id: Optional ID of invoice order link being edited

    Returns:
        The newly created InvoiceOrderLink instance

    Raises:
        ValidationError: If invoice has no PK or total would exceed invoice amount
    """
    from invoice.models import InvoiceOrderLink
    from django.db import transaction

    if not invoice.pk:
        raise ValidationError("La factura debe guardarse primero antes de añadir ventas.")

    validate_invoice_order_total(
        invoice=invoice,
        order=order,
        exclude_invoice_order_link_id=exclude_invoice_order_link_id,
    )

    with transaction.atomic():
        link = InvoiceOrderLink.objects.create(invoice=invoice, order=order)
    return link


def validate_invoice_orders_total_limit(invoice_amount: Decimal, order_amounts: List[Decimal]) -> None:
    """Validate that the sum of selected orders does not exceed invoice amount."""
    total_selected = sum(order_amounts, Decimal('0'))
    if total_selected > invoice_amount:
        raise ValidationError(
            f"La suma de montos de las ventas asociadas ({total_selected}) "
            f"excede el monto de la factura ({invoice_amount})."
        )


def validate_invoice_order_total(invoice, order, exclude_invoice_order_link_id=None) -> None:
    """
    Validate that adding an order to an invoice won't exceed the invoice amount.

    Args:
        invoice: Invoice instance
        order: Order instance to add
        exclude_invoice_order_link_id: Optional ID of invoice order link being edited

    Raises:
        ValidationError: If total would exceed invoice amount
    """
    from invoice.models import InvoiceOrderLink

    # Unsaved invoices have no existing links yet. Avoid filtering by an unsaved
    # model instance because Django raises ValueError for related filters.
    if getattr(invoice, 'pk', None):
        existing_orders = InvoiceOrderLink.objects.filter(invoice=invoice)

        if exclude_invoice_order_link_id:
            existing_orders = existing_orders.exclude(pk=exclude_invoice_order_link_id)

        total_existing = existing_orders.aggregate(
            total=Sum('order__total_amount')
        )['total'] or Decimal('0')
    else:
        total_existing = Decimal('0')

    new_amount = order.total_amount or Decimal('0')
    max_amount = invoice.amount

    if total_existing + new_amount > max_amount:
        raise ValidationError(
            f"La suma de montos de las ventas asociadas"
            f"excede el monto de la factura ({max_amount}). Considere dividir un pedido grande en varios o aumentar el monto de la factura."
        )


def get_invoiceable_orders_for_client(
    client: Client,
    include_order_id: Optional[int] = None,
    as_dict: bool = False,
) -> List:
    """
    Get all invoiceable orders for a specific client.

    Eligibility rules:
    - Order belongs to the provided client
    - Order status is COMPLETED
    - Order has no invoice link (unless include_order_id is provided for edit mode)

    Args:
        client: Client instance or client ID
        include_order_id: Optional order ID to keep in queryset during edit mode
        as_dict: If True, return list of dicts for JSON serialization

    Returns:
        QuerySet or list of dicts with order information
    """
    orders = Order.objects.unbilled_for_client(
        client=client,
        exclude_order_id=include_order_id,
    )

    if not as_dict:
        return orders

    # Return as dict for JSON serialization
    return [
        {
            'id': order.id,
            'order_date': order.order_date.isoformat(),
            'total_amount': str(order.total_amount),
            'display': f"Order #{order.id} - {order.order_date.strftime('%Y-%m-%d')} - ${order.total_amount} - {order.get_status_display()}"
        }
        for order in orders
    ]


# Date Range Utilities


def get_date_range_from_preset(preset: str, custom_start: Optional[str] = None,
                               custom_end: Optional[str] = None) -> Tuple[date, date]:
    """
    Get date range based on preset or custom dates.

    Args:
        preset: Date preset name ('today', 'this_week', 'this_month', 'next_7_days', or empty for custom)
        custom_start: Custom start date string (YYYY-MM-DD format)
        custom_end: Custom end date string (YYYY-MM-DD format)

    Returns:
        Tuple of (start_date, end_date)
    """
    today = date.today()

    if preset == 'today':
        return today, today

    elif preset == 'this_week':
        start_date = today - timedelta(days=today.weekday())
        end_date = start_date + timedelta(days=6)
        return start_date, end_date

    elif preset == 'this_month':
        start_date = today.replace(day=1)
        last_day = monthrange(today.year, today.month)[1]
        end_date = today.replace(day=last_day)
        return start_date, end_date

    elif preset == 'next_7_days':
        return today, today + timedelta(days=7)

    else:
        # Custom date range
        try:
            start_date = datetime.strptime(custom_start, '%Y-%m-%d').date() if custom_start else today
        except (ValueError, TypeError):
            start_date = today

        try:
            end_date = datetime.strptime(custom_end, '%Y-%m-%d').date() if custom_end else today + timedelta(days=7)
        except (ValueError, TypeError):
            end_date = today + timedelta(days=7)

        return start_date, end_date

def delete_billing_frequency_for_client(client_id: int) -> None:
    """
    Disable billing frequency for a specific client.

    Args:
        client_id: ID of the client to update
    """
    try:
        billing_frequency = InvoiceSchedule.objects.get(client_id=client_id)
        billing_frequency.delete()
    except InvoiceSchedule.DoesNotExist:
        pass  # If no billing frequency exists, nothing to disable

def delete_billing_data_for_client(client_id: int) -> None:
    """
    Disable billing data for a specific client by setting their billing data to inactive.

    Args:
        client_id: ID of the client to update
    """
    billing_data = InvoiceData.objects.filter(client_id=client_id).first()
    if billing_data:
        billing_data.delete() 

def disable_billing_for_client(client_id: int) -> None:
    """
    Disable recurring billing for a specific client by setting their billing frequency to inactive.

    Args:
        client_id: ID of the client to update
    """
    delete_billing_frequency_for_client(client_id)


def create_invoice_from_orders(orders: List, client: Client) -> 'invoice.models.Invoice':
    """
    Create an Invoice from a list of Order instances.

    The invoice amount is set to the sum of all order total_amounts.
    Each order gets an InvoiceOrderLink connecting it to the new invoice.
    Identifier and folio are auto-generated placeholders for the user to update.

    Args:
        orders: List of Order instances (must be COMPLETED and unbilled)
        client: Client the invoice belongs to

    Returns:
        The newly created Invoice instance

    Raises:
        ValidationError: If orders list is empty or orders belong to different clients
    """
    import uuid
    from django.db import transaction
    from invoice.models import Invoice, InvoiceOrderLink

    if not orders:
        raise ValidationError("Debe seleccionar al menos un pedido.")

    clients = {order.client for order in orders}
    #Validate if all clients are corporate and if are branches they must belong to the same corporate
    clients_corporate = []
    
    for client in clients:
        if client.corporate is not None:
            clients_corporate.append(client.corporate)
        else:
            clients_corporate.append(client)

    if len(set(clients_corporate)) > 1:
        raise ValidationError("Todos los pedidos deben pertenecer al mismo cliente corporativo.")

    for order_client in clients:
        validate_client_invoice_generation_requirements(order_client)

    total = sum(o.total_amount for o in orders)
    short_id = uuid.uuid4().hex[:8].upper()

    with transaction.atomic():
        invoice = Invoice.objects.create(
            client=client,
            amount=total,
            auto_amount=True,
            identifier=f'BORRADOR-{short_id}',
            folio=f'BORRADOR-{short_id}',
        )
        for order in orders:
            InvoiceOrderLink.objects.create(invoice=invoice, order=order)

    return invoice


def sync_invoice_amount(invoice: 'invoice.models.Invoice') -> None:
    """
    Recalculate Invoice.amount from the sum of all currently linked order total_amounts.

    Intended to be called from InvoiceAdmin.save_related() so every edit to the
    inline order links keeps the invoice amount automatically consistent.

    Args:
        invoice: Invoice instance whose amount will be updated in-place and in the DB
    """
    from invoice.models import InvoiceOrderLink

    total = InvoiceOrderLink.objects.filter(invoice=invoice).aggregate(
        total=Sum('order__total_amount')
    )['total'] or Decimal('0')

    type(invoice).objects.filter(pk=invoice.pk).update(amount=total)
    invoice.amount = total
