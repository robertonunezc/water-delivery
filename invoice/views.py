from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.db import transaction
from invoice.models import Invoice
from clients.models import Client
from django.core.paginator import Paginator
from django.db.models import Sum, Q, Count
from datetime import date

# Existing API Views

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


# Custom Admin Dashboard Views

@staff_member_required
def list_invoices_admin(request):
    # Base queryset
    invoices = Invoice.objects.select_related('client').prefetch_related('invoice_links__order__payments')

    # Apply filters
    client_filter = request.GET.get('client', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    search_query = request.GET.get('search', '').strip()

    if client_filter:
        try:
            client_id = int(client_filter)
            invoices = invoices.filter(client_id=client_id)
        except (ValueError, TypeError):
            pass

    if date_from:
        try:
            from datetime import datetime
            date_from_obj = datetime.strptime(date_from, '%Y-%m-%d').date()
            invoices = invoices.filter(date__date__gte=date_from_obj)
        except ValueError:
            pass

    if date_to:
        try:
            from datetime import datetime
            date_to_obj = datetime.strptime(date_to, '%Y-%m-%d').date()
            invoices = invoices.filter(date__date__lte=date_to_obj)
        except ValueError:
            pass

    if search_query:
        invoices = invoices.filter(
            Q(identifier__icontains=search_query) |
            Q(folio__icontains=search_query) |
            Q(client__name__icontains=search_query)
        ).distinct()

    invoices = invoices.order_by('-date', '-id')

    # KPI stats
    total_invoices = invoices.count()
    
    # Filter options
    all_clients = Client.objects.filter(invoices__isnull=False).distinct().order_by('name')

    # Pagination
    paginator = Paginator(invoices, 15)
    page_number = request.GET.get('page', 1)
    invoices_page = paginator.get_page(page_number)

    context = {
        'invoices': invoices_page,
        'all_clients': all_clients,
        'filters': {
            'client': client_filter,
            'date_from': date_from,
            'date_to': date_to,
            'search': search_query,
        },
        'has_filters': any([client_filter, date_from, date_to, search_query]),
        'total_invoices': total_invoices,
        'today': date.today(),
    }
    return render(request, 'billing/admin/invoices_list.html', context)


@staff_member_required
def create_invoice_admin(request):
    from invoice.forms import InvoiceForm
    from django.contrib import messages

    if request.method == 'POST':
        form = InvoiceForm(request.POST, request.FILES)
        if form.is_valid():
            invoice = form.save()
            messages.success(request, f'Factura #{invoice.id} creada exitosamente. Ahora puede vincular ventas.')
            return redirect('admin_edit_invoice', pk=invoice.pk)
    else:
        form = InvoiceForm()

    context = {
        'form': form,
        'is_create': True,
    }
    return render(request, 'billing/admin/invoice_create.html', context)


@staff_member_required
@transaction.atomic
def edit_invoice_admin(request, pk):
    from invoice.models import Invoice, InvoiceOrderLink
    from invoice.forms import InvoiceForm, InvoiceOrderLinkForm
    from invoice.services import get_invoiceable_orders_for_client, add_order_to_invoice, sync_invoice_amount
    from django.contrib import messages
    from django.core.exceptions import ValidationError

    invoice = get_object_or_404(Invoice, pk=pk)

    if request.method == 'POST':
        # Check if the post action is adding an order link
        if 'add_order_link' in request.POST:
            link_form = InvoiceOrderLinkForm(request.POST, client=invoice.client)
            if link_form.is_valid():
                order = link_form.cleaned_data['order']
                try:
                    add_order_to_invoice(invoice=invoice, order=order)
                    if invoice.auto_amount:
                        sync_invoice_amount(invoice)
                    messages.success(request, f'Pedido #{order.id} vinculado correctamente a la factura.')
                except ValidationError as e:
                    messages.error(request, f'Error al vincular el pedido: {str(e)}')
            else:
                messages.error(request, 'Formulario de pedido no válido o pedido ya vinculado.')
            return redirect('admin_edit_invoice', pk=invoice.pk)

        # Basic invoice form save
        form = InvoiceForm(request.POST, request.FILES, instance=invoice)
        if form.is_valid():
            invoice = form.save()
            if invoice.auto_amount:
                sync_invoice_amount(invoice)
            messages.success(request, 'Datos de la factura actualizados correctamente.')
            return redirect('admin_edit_invoice', pk=invoice.pk)
    else:
        form = InvoiceForm(instance=invoice)

    # Prepare linked orders and available orders to link
    linked_orders = invoice.invoice_links.select_related('order').all()
    
    # Form to add a new link
    link_form = InvoiceOrderLinkForm(client=invoice.client)
    
    # Get raw billable orders as well for dynamic JS loading
    billable_orders = get_invoiceable_orders_for_client(client=invoice.client, as_dict=True)

    context = {
        'invoice': invoice,
        'form': form,
        'link_form': link_form,
        'linked_orders': linked_orders,
        'billable_orders': billable_orders,
        'is_create': False,
    }
    return render(request, 'billing/admin/invoice_edit.html', context)


@staff_member_required
@transaction.atomic
def remove_order_link_admin(request, pk, link_pk):
    from invoice.models import Invoice, InvoiceOrderLink
    from invoice.services import sync_invoice_amount
    from django.contrib import messages

    invoice = get_object_or_404(Invoice, pk=pk)
    link = get_object_or_404(InvoiceOrderLink, pk=link_pk, invoice=invoice)

    order_id = link.order.id
    link.delete()

    if invoice.auto_amount:
        sync_invoice_amount(invoice)

    messages.success(request, f'Pedido #{order_id} desvinculado correctamente de la factura.')
    return redirect('admin_edit_invoice', pk=invoice.pk)