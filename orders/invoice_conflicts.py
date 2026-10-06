from collections.abc import Iterable

from django.urls import reverse
from django.utils.html import format_html, format_html_join
from django.utils.safestring import SafeString

from invoice.models import (
    InvoiceOrderLink,
    RESERVING_INVOICE_STATUSES,
)


def get_reserved_invoice_links_for_orders(
    order_ids: Iterable[int],
) -> list[InvoiceOrderLink]:
    """Return draft/active invoice links that reserve the given orders."""
    ids = list(order_ids)
    if not ids:
        return []

    return list(
        InvoiceOrderLink.objects.filter(
            order_id__in=ids,
            invoice__status__in=RESERVING_INVOICE_STATUSES,
        )
        .select_related('invoice')
        .order_by('order_id', 'invoice_id')
    )


def build_reserved_invoice_conflict_message(
    invoice_links: Iterable[InvoiceOrderLink],
) -> SafeString:
    """Build a safe HTML message with links to conflicting invoices."""
    items = [
        (
            link.order_id,
            reverse('admin_edit_invoice', args=[link.invoice_id]),
            f'{link.invoice.identifier}-{link.invoice.folio}',
        )
        for link in invoice_links
    ]
    linked_orders = format_html_join(
        ', ',
        '#{} (<a href="{}">Factura {}</a>)',
        items,
    )
    return format_html(
        'Los siguientes pedidos ya están vinculados a una factura '
        'en borrador o activa: {}.',
        linked_orders,
    )
