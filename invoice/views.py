from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.contrib.auth.decorators import login_required

# Create your views here.

@login_required
def invoiceable_orders(request, client_pk):
    from invoice.services import get_invoiceable_orders_for_client
    from clients.models import Client

    client = get_object_or_404(Client, pk=client_pk)

    include_order_id = request.GET.get('include_order_id')
    if include_order_id:
        try:
            include_order_id = int(include_order_id)
        except (TypeError, ValueError):
            include_order_id = None

    orders_data = get_invoiceable_orders_for_client(
        client=client,
        include_order_id=include_order_id,
        as_dict=True,
    )
    return JsonResponse({'orders': orders_data})


@login_required
def invoice_client(request, invoice_id):
    from invoice.models import Invoice

    invoice = get_object_or_404(Invoice, pk=invoice_id)
    return JsonResponse({
        'client_id': invoice.client_id,
        'client_name': invoice.client.name,
    })