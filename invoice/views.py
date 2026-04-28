from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.contrib.auth.decorators import login_required

# Create your views here.

@login_required
def invoiceable_orders(request, client_pk):
    from invoice.services import get_invoiceable_orders_for_client
    from invoice.models import Invoice
    from clients.models import Client

    client = get_object_or_404(Client, pk=client_pk)
    invoice_id = request.GET.get('invoice_id')

    invoice = None
    if invoice_id:
        invoice = Invoice.objects.filter(pk=invoice_id).first()

    emitted_at = None
    if invoice:
        emitted_at = invoice.emmited_at or invoice.date

    if not emitted_at:
        return JsonResponse({'orders': []})

    orders_data = get_invoiceable_orders_for_client(
        client=client,
        emitted_at=emitted_at,
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