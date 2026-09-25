from datetime import date
from decimal import Decimal

from clients.models import Client
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_POST
from invoice.models import Invoice

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
    scope = request.GET.get('scope', 'exact')

    orders_data = get_invoiceable_orders_for_client(
        client=client,
        include_order_id=include_order_id,
        scope=scope,
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
    status_filter = request.GET.get('status', '')
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

    if status_filter in {'ACTIVE', 'CANCELLED'}:
        invoices = invoices.filter(status=status_filter)

    invoices = invoices.order_by('-date', '-id')

    # KPI stats
    total_invoices = invoices.count()
    
    # Filter options
    all_clients = Client.objects.filter(invoices__isnull=False).distinct().order_by('name')

    # Pagination
    paginator = Paginator(invoices, 15)
    page_number = request.GET.get('page', 1)
    invoices_page = paginator.get_page(page_number)
    page_stats = {
        'total_amount': sum(
            (
                invoice.amount
                for invoice in invoices_page
                if invoice.status == 'ACTIVE'
            ),
            Decimal('0.00'),
        ),
        'active_count': sum(
            1 for invoice in invoices_page if invoice.status == 'ACTIVE'
        ),
        'cancelled_count': sum(
            1 for invoice in invoices_page if invoice.status == 'CANCELLED'
        ),
    }

    context = {
        'invoices': invoices_page,
        'page_stats': page_stats,
        'all_clients': all_clients,
        'filters': {
            'client': client_filter,
            'date_from': date_from,
            'date_to': date_to,
            'status': status_filter,
            'search': search_query,
        },
        'has_filters': any([
            client_filter,
            date_from,
            date_to,
            status_filter,
            search_query,
        ]),
        'total_invoices': total_invoices,
        'today': date.today(),
    }
    return render(request, 'billing/admin/invoices_list.html', context)


@staff_member_required
def create_invoice_admin(request):
    from invoice.forms import InvoiceCreateForm
    from invoice.services import create_invoice_with_orders
    from django.contrib import messages
    from django.core.exceptions import ValidationError

    if request.method == 'POST':
        form = InvoiceCreateForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                invoice = create_invoice_with_orders(
                    invoice=form.save(commit=False),
                    orders=list(form.cleaned_data['orders']),
                )
            except ValidationError as exc:
                form.add_error(None, exc)
            else:
                messages.success(
                    request,
                    f'Factura #{invoice.id} creada exitosamente con sus ventas vinculadas.',
                )
                return redirect('admin_edit_invoice', pk=invoice.pk)
    else:
        form = InvoiceCreateForm()

    context = {
        'form': form,
        'is_create': True,
    }
    return render(request, 'billing/admin/invoice_create.html', context)


@staff_member_required
@require_POST
def cancel_invoice_admin(request, pk):
    from django.contrib import messages
    from invoice.services import cancel_invoice

    invoice = get_object_or_404(Invoice, pk=pk)
    was_cancelled = invoice.status == 'CANCELLED'
    cancel_invoice(invoice)

    if was_cancelled:
        messages.info(request, f'La factura #{invoice.id} ya estaba cancelada.')
    else:
        messages.success(request, f'Factura #{invoice.id} cancelada correctamente.')

    next_url = request.POST.get('next', '')
    if next_url and url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return redirect(next_url)
    return redirect('admin_invoices')


@staff_member_required
@require_GET
def edit_invoice_admin(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)
    linked_orders = invoice.invoice_links.select_related('order').all()

    context = {
        'invoice': invoice,
        'linked_orders': linked_orders,
    }
    return render(request, 'billing/admin/invoice_edit.html', context)
