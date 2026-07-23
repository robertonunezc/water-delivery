from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db.models import Sum, Q
from django.db.models.query import QuerySet
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.contrib import messages
from django.forms import inlineformset_factory
from django.urls import reverse
from decimal import Decimal, InvalidOperation
from typing import Any, List
from urllib.parse import urlencode
from .models import Client, Address, Contact, InvoiceData, ClientCreditConfig, InvoiceSchedule
from .forms import (
    ManualCreditTransactionForm,
    ManualBalanceTransactionForm,
    ClientCoreForm,
    ClientCreditPolicyForm,
    ContactForm,
    InvoiceDataForm,
    ClientRecurringBillingForm,
    InvoiceScheduleForm,
    ClientCreditConfigForm,
    AddressInlineForm,
)
from .services import get_upcoming_route_orders, get_recent_completed_route_orders
from .services.client_detail_service import build_client_detail_snapshot
from .services.client_service import initialize_branch_credit_from_corporate
from .services.corporate_branch_service import build_corporate_branch_workspace
from orders.models import Order
from payment import services as payment_services
from payment.models import PAYMENT_METHOD_CHOICES
from product.services import ensure_client_product_prices
from routes.forms import ClientRouteAssignmentForm
from routes.models import RouteClient


def _is_admin_user(user) -> bool:
    return user.is_authenticated and user.is_staff


def _get_address_formset(*, data=None, instance=None):
    formset_cls = inlineformset_factory(
        Client,
        Address,
        form=AddressInlineForm,
        extra=1,
        can_delete=True,
    )
    return formset_cls(data=data, instance=instance, prefix='addresses')


def _get_contact_formset(*, data=None, instance=None):
    formset_cls = inlineformset_factory(
        Client,
        Contact,
        form=ContactForm,
        extra=1,
        can_delete=True,
    )
    return formset_cls(data=data, instance=instance, prefix='contacts')


def _get_route_assignment_formset(*, data: Any = None, instance: Client | None = None) -> Any:
    formset_cls = inlineformset_factory(
        Client,
        RouteClient,
        form=ClientRouteAssignmentForm,
        extra=1,
        can_delete=True,
    )
    return formset_cls(data=data, instance=instance, prefix='routes')


def _copy_delivery_to_billing_if_missing(client: Client) -> bool:
    if client.addresses.filter(type='billing').exists():
        return False

    delivery_address = client.addresses.filter(type='delivery').order_by('id').first()
    if not delivery_address:
        return False

    Address.objects.create(
        client=client,
        type='billing',
        street=delivery_address.street,
        exterior_number=delivery_address.exterior_number,
        interior_number=delivery_address.interior_number,
        locality=delivery_address.locality,
        municipality=delivery_address.municipality,
        state=delivery_address.state,
        zip_code=delivery_address.zip_code,
        country=delivery_address.country,
        reference=delivery_address.reference,
        active=delivery_address.active,
    )
    return True


def _submission_has_billing_address(formset) -> bool:
    for form in formset.forms:
        cleaned_data = getattr(form, 'cleaned_data', None)
        if not cleaned_data:
            continue
        if cleaned_data.get('DELETE', False):
            continue
        if cleaned_data.get('type') == 'billing':
            return True
    return False


def _submission_deletes_billing_address(formset) -> bool:
    for form in formset.forms:
        cleaned_data = getattr(form, 'cleaned_data', None)
        if not cleaned_data:
            continue
        if not cleaned_data.get('DELETE', False):
            continue

        instance = form.instance
        if instance and instance.pk and instance.type == 'billing':
            return True
    return False


def _build_client_v2_context(request, *, client=None, active_tab='basic', forms_override=None):
    forms_override = forms_override or {}

    core_form = forms_override.get('core_form') or ClientCoreForm(instance=client)
    credit_policy_form = forms_override.get('credit_policy_form') or ClientCreditPolicyForm(
        instance=client,
        prefix='credit_policy',
    )

    address_formset = forms_override.get('address_formset')
    if address_formset is None and client is not None:
        address_formset = _get_address_formset(instance=client)

    contact_formset = forms_override.get('contact_formset')
    if contact_formset is None and client is not None:
        contact_formset = _get_contact_formset(instance=client)

    route_assignment_formset = forms_override.get('route_assignment_formset')
    if route_assignment_formset is None and client is not None:
        route_assignment_formset = _get_route_assignment_formset(instance=client)

    invoice_data_instance = getattr(client, 'invoice_data', None) if client else None
    invoice_schedule_instance = getattr(client, 'invoice_schedule', None) if client else None
    if client and invoice_schedule_instance is None:
        invoice_schedule_instance = InvoiceSchedule(client=client)
    credit_config_instance = getattr(client, 'credit_config', None) if client else None
    if client and credit_config_instance is None:
        credit_config_instance = ClientCreditConfig(
            client=client,
            payment_term_type=(
                'invoice_due' if client.requires_billing else 'monthly_cutoff'
            ),
        )

    invoice_data_form = forms_override.get('invoice_data_form') or InvoiceDataForm(instance=invoice_data_instance, prefix='invoice_data')
    recurring_billing_form = forms_override.get('recurring_billing_form') or ClientRecurringBillingForm(instance=client, prefix='recurring_billing')
    invoice_schedule_form = forms_override.get('invoice_schedule_form') or InvoiceScheduleForm(instance=invoice_schedule_instance, prefix='invoice_schedule')
    credit_config_form = forms_override.get('credit_config_form') or ClientCreditConfigForm(instance=credit_config_instance, prefix='credit_config')

    billing_enabled = bool(client)
    billing_read_only = bool(
        client
        and client.type == 'branch'
    )
    billing_data_disabled = not billing_enabled or billing_read_only
    billing_frequency_disabled = billing_data_disabled or not bool(client and client.requires_billing)
    credit_read_only = bool(
        client
        and client.type == 'branch'
        and not client.credit_override_enabled
    )

    if billing_data_disabled:
        for field in invoice_data_form.fields.values():
            field.disabled = True

    if billing_frequency_disabled:
        for field in invoice_schedule_form.fields.values():
            field.disabled = True

    if credit_read_only:
        for field in credit_policy_form.fields.values():
            field.disabled = True
        for field in credit_config_form.fields.values():
            field.disabled = True

    return {
        'client': client,
        'active_tab': active_tab,
        'core_form': core_form,
        'credit_policy_form': credit_policy_form,
        'address_formset': address_formset,
        'contact_formset': contact_formset,
        'route_assignment_formset': route_assignment_formset,
        'has_delivery_address': client.has_delivery_address() if client else False,
        'invoice_data_form': invoice_data_form,
        'recurring_billing_form': recurring_billing_form,
        'invoice_schedule_form': invoice_schedule_form,
        'credit_config_form': credit_config_form,
        'billing_enabled': billing_enabled,
        'billing_read_only': billing_read_only,
        'billing_data_disabled': billing_data_disabled,
        'billing_frequency_disabled': billing_frequency_disabled,
        'credit_read_only': credit_read_only,
        'effective_billing_data': client.billing_info.effective.data if client else None,
        'effective_billing_address': client.billing_info.effective.address if client else None,
        'effective_billing_frequency': client.billing_info.effective.frequency if client else None,
    }

@login_required
def create(request):
    return redirect('clients:create_v2')


@user_passes_test(_is_admin_user)
def create_v2(request):
    active_tab = 'basic'
    if request.method == 'POST':
        form = ClientCoreForm(request.POST)
        if form.is_valid():
            client = form.save()
            initialize_branch_credit_from_corporate(client)
            pricing_summary = ensure_client_product_prices(client)
            if pricing_summary.get('created_count', 0):
                messages.info(
                    request,
                    f"Se crearon {pricing_summary['created_count']} precios de producto para el cliente.",
                )
            messages.success(request, 'Cliente creado correctamente. Ahora puede completar las demás pestañas.')
            if request.path.startswith('/administrador/'):
                edit_url = reverse('admin_edit_client', kwargs={'pk': client.pk})
            else:
                edit_url = reverse('clients:edit_v2', kwargs={'pk': client.pk})
            return redirect(f"{edit_url}?tab=basic")

        context = {
            'client': None,
            'active_tab': active_tab,
            'core_form': form,
            'is_create': True,
        }
        return render(request, 'clients/client_form_v2.html', context)

    form = ClientCoreForm(
        initial={
            'active': True,
            'type': 'branch',
            'requires_billing': False,
            'credit_override_enabled': False,
        }
    )
    context = {
        'client': None,
        'active_tab': active_tab,
        'core_form': form,
        'is_create': True,
    }
    return render(request, 'clients/client_form_v2.html', context)


@user_passes_test(_is_admin_user)
def edit_v2(request, pk):
    client = get_object_or_404(Client, pk=pk)
    active_tab = request.GET.get('tab', 'basic')

    if request.method == 'POST':
        section = request.POST.get('section', 'basic')
        active_tab = section

        if section == 'basic':
            core_form = ClientCoreForm(request.POST, instance=client)
            if core_form.is_valid():
                core_form.save()
                if not client.requires_billing and hasattr(client, 'invoice_schedule'):
                    client.invoice_schedule.is_active = False
                    client.invoice_schedule.save()
                messages.success(request, 'Datos básicos actualizados correctamente.')
                if client.requires_billing and not client.billing_info.effective.has_address:
                    messages.warning(request, '⚠️ Advertencia: El cliente requiere facturación pero no se encontró un domicilio de tipo FISCAL.')
                if request.path.startswith('/administrador/'):
                    return redirect(f"{reverse('admin_edit_client', kwargs={'pk': client.pk})}?tab=basic")
                return redirect(f"{reverse('clients:edit_v2', kwargs={'pk': client.pk})}?tab=basic")
            context = _build_client_v2_context(
                request,
                client=client,
                active_tab=active_tab,
                forms_override={'core_form': core_form},
            )
            return render(request, 'clients/client_form_v2.html', context)

        if section == 'recurring_billing':
            recurring_billing_form = ClientRecurringBillingForm(
                request.POST,
                instance=client,
                prefix='recurring_billing',
            )
            if recurring_billing_form.is_valid():
                recurring_billing_form.save()
                if not client.requires_billing and hasattr(client, 'invoice_schedule'):
                    client.invoice_schedule.is_active = False
                    client.invoice_schedule.save()
                messages.success(request, 'Configuración de facturación recurrente actualizada correctamente.')
                if request.path.startswith('/administrador/'):
                    return redirect(f"{reverse('admin_edit_client', kwargs={'pk': client.pk})}?tab=billing")
                return redirect(f"{reverse('clients:edit_v2', kwargs={'pk': client.pk})}?tab=billing")
            context = _build_client_v2_context(
                request,
                client=client,
                active_tab='billing',
                forms_override={'recurring_billing_form': recurring_billing_form},
            )
            return render(request, 'clients/client_form_v2.html', context)

        if section == 'addresses':
            address_formset = _get_address_formset(data=request.POST, instance=client)
            if address_formset.is_valid():
                wants_copy = request.POST.get('copy_address_for_all_inlines') == 'on'
                submission_has_billing = _submission_has_billing_address(address_formset)
                submission_deletes_billing = _submission_deletes_billing_address(address_formset)

                address_formset.save()
                if wants_copy and not submission_has_billing and not submission_deletes_billing:
                    if _copy_delivery_to_billing_if_missing(client):
                        messages.success(request, 'Se creó una dirección fiscal copiando la primera dirección de entrega.')
                elif wants_copy and submission_deletes_billing:
                    messages.info(request, 'No se creó dirección fiscal automática porque en esta operación se eliminó una dirección fiscal.')
                messages.success(request, 'Direcciones actualizadas correctamente.')
                if client.requires_billing and not client.billing_info.effective.has_address:
                    messages.warning(request, '⚠️ Advertencia: El cliente requiere facturación pero no se encontró un domicilio de tipo FISCAL.')
                if request.path.startswith('/administrador/'):
                    return redirect(f"{reverse('admin_edit_client', kwargs={'pk': client.pk})}?tab=addresses")
                return redirect(f"{reverse('clients:edit_v2', kwargs={'pk': client.pk})}?tab=addresses")
            context = _build_client_v2_context(
                request,
                client=client,
                active_tab=active_tab,
                forms_override={'address_formset': address_formset},
            )
            return render(request, 'clients/client_form_v2.html', context)

        if section == 'contacts':
            contact_formset = _get_contact_formset(data=request.POST, instance=client)
            if contact_formset.is_valid():
                contact_formset.save()
                messages.success(request, 'Contactos actualizados correctamente.')
                if request.path.startswith('/administrador/'):
                    return redirect(f"{reverse('admin_edit_client', kwargs={'pk': client.pk})}?tab=contacts")
                return redirect(f"{reverse('clients:edit_v2', kwargs={'pk': client.pk})}?tab=contacts")
            context = _build_client_v2_context(
                request,
                client=client,
                active_tab=active_tab,
                forms_override={'contact_formset': contact_formset},
            )
            return render(request, 'clients/client_form_v2.html', context)

        if section == 'routes':
            route_assignment_formset = _get_route_assignment_formset(
                data=request.POST,
                instance=client,
            )
            if route_assignment_formset.is_valid():
                route_assignment_formset.save()
                messages.success(request, 'Asignaciones de ruta actualizadas correctamente.')
                if request.path.startswith('/administrador/'):
                    return redirect(f"{reverse('admin_edit_client', kwargs={'pk': client.pk})}?tab=routes")
                return redirect(f"{reverse('clients:edit_v2', kwargs={'pk': client.pk})}?tab=routes")
            context = _build_client_v2_context(
                request,
                client=client,
                active_tab='routes',
                forms_override={'route_assignment_formset': route_assignment_formset},
            )
            return render(request, 'clients/client_form_v2.html', context)

        if section in ['billing_data', 'billing_frequency']:
            if section == 'billing_data':
                if client.type == 'branch':
                    messages.warning(request, 'Esta sucursal hereda los datos de facturación del corporativo y no puede editarlos aquí.')
                    if request.path.startswith('/administrador/'):
                        return redirect(f"{reverse('admin_edit_client', kwargs={'pk': client.pk})}?tab=billing")
                    return redirect(f"{reverse('clients:edit_v2', kwargs={'pk': client.pk})}?tab=billing")

                form = InvoiceDataForm(request.POST, instance=getattr(client, 'invoice_data', None), prefix='invoice_data')
                if form.is_valid():
                    invoice_data = form.save(commit=False)
                    invoice_data.client = client
                    invoice_data.save()
                    messages.success(request, 'Datos de facturación actualizados correctamente.')
                    if request.path.startswith('/administrador/'):
                        return redirect(f"{reverse('admin_edit_client', kwargs={'pk': client.pk})}?tab=billing")
                    return redirect(f"{reverse('clients:edit_v2', kwargs={'pk': client.pk})}?tab=billing")
                context = _build_client_v2_context(
                    request,
                    client=client,
                    active_tab='billing',
                    forms_override={'invoice_data_form': form},
                )
                return render(request, 'clients/client_form_v2.html', context)

            if client.type == 'branch':
                messages.warning(request, 'Esta sucursal hereda la configuración de facturación del corporativo y no puede editarla aquí.')
                if request.path.startswith('/administrador/'):
                    return redirect(f"{reverse('admin_edit_client', kwargs={'pk': client.pk})}?tab=billing")
                return redirect(f"{reverse('clients:edit_v2', kwargs={'pk': client.pk})}?tab=billing")

            if not client.requires_billing:
                messages.warning(request, 'Active "Requiere facturación recurrente" en Datos Básicos para configurar la frecuencia de facturación.')
                if request.path.startswith('/administrador/'):
                    return redirect(f"{reverse('admin_edit_client', kwargs={'pk': client.pk})}?tab=billing")
                return redirect(f"{reverse('clients:edit_v2', kwargs={'pk': client.pk})}?tab=billing")

            schedule_instance = getattr(client, 'invoice_schedule', None)
            if schedule_instance is None:
                schedule_instance = InvoiceSchedule(client=client)
            form = InvoiceScheduleForm(request.POST, instance=schedule_instance, prefix='invoice_schedule')
            if form.is_valid():
                schedule = form.save(commit=False)
                schedule.client = client
                schedule.save()
                messages.success(request, 'Frecuencia de facturación actualizada correctamente.')
                if request.path.startswith('/administrador/'):
                    return redirect(f"{reverse('admin_edit_client', kwargs={'pk': client.pk})}?tab=billing")
                return redirect(f"{reverse('clients:edit_v2', kwargs={'pk': client.pk})}?tab=billing")
            context = _build_client_v2_context(
                request,
                client=client,
                active_tab='billing',
                forms_override={'invoice_schedule_form': form},
            )
            return render(request, 'clients/client_form_v2.html', context)

        if section == 'credit':
            if client.type == 'branch' and not client.credit_override_enabled:
                messages.warning(request, 'La configuración de crédito se administra desde el corporativo para esta sucursal.')
                if request.path.startswith('/administrador/'):
                    return redirect(f"{reverse('admin_edit_client', kwargs={'pk': client.pk})}?tab=credit")
                return redirect(f"{reverse('clients:edit_v2', kwargs={'pk': client.pk})}?tab=credit")

            credit_policy_form = ClientCreditPolicyForm(request.POST, instance=client, prefix='credit_policy')
            credit_config_instance = getattr(client, 'credit_config', None)
            if credit_config_instance is None:
                credit_config_instance = ClientCreditConfig(
                    client=client,
                    payment_term_type=(
                        'invoice_due' if client.requires_billing else 'monthly_cutoff'
                    ),
                )
            credit_config_form = ClientCreditConfigForm(
                request.POST,
                instance=credit_config_instance,
                prefix='credit_config',
            )
            if credit_policy_form.is_valid() and credit_config_form.is_valid():
                credit_policy_form.save()
                credit_config = credit_config_form.save(commit=False)
                credit_config.client = client
                credit_config.save()
                messages.success(request, 'Configuración de crédito actualizada correctamente.')
                if request.path.startswith('/administrador/'):
                    return redirect(f"{reverse('admin_edit_client', kwargs={'pk': client.pk})}?tab=credit")
                return redirect(f"{reverse('clients:edit_v2', kwargs={'pk': client.pk})}?tab=credit")
            context = _build_client_v2_context(
                request,
                client=client,
                active_tab='credit',
                forms_override={
                    'credit_policy_form': credit_policy_form,
                    'credit_config_form': credit_config_form,
                },
            )
            return render(request, 'clients/client_form_v2.html', context)

    context = _build_client_v2_context(request, client=client, active_tab=active_tab)
    context['is_create'] = False
    return render(request, 'clients/client_form_v2.html', context)
@login_required
def list_admin(request):
    context = get_clients(request)
    return render(request, 'admin/clients/list.html', context)

@login_required
def list(request):
    # Get search query from request
    context = get_clients(request)
    return render(request, 'list_clients.html', context)


CLIENT_DETAIL_PAGE_SIZE = 10


def _paginate_client_detail_items(request: Any, items: Any, *, page_param: str) -> Any:
    paginator = Paginator(items, CLIENT_DETAIL_PAGE_SIZE)
    return paginator.get_page(request.GET.get(page_param, 1))


def _get_client_detail_invoices(client: Client) -> QuerySet[Any]:
    """Return invoices linked to orders owned by this client."""
    from invoice.models import Invoice

    if not client.requires_billing:
        return Invoice.objects.none()

    return (
        Invoice.objects.filter(invoice_links__order__client=client)
        .select_related('client')
        .prefetch_related('invoice_links__order__payments')
        .distinct()
        .order_by('-date', '-id')
    )


def _payment_status_class(status: str) -> str:
    if status == 'completed':
        return 'success'
    if status == 'pending':
        return 'warning'
    return 'danger'


def _payment_history_item(payment: Any) -> dict[str, Any]:
    return {
        'type': 'payment',
        'id': payment.id,
        'date': payment.date,
        'amount': payment.amount,
        'method': payment.get_method_display(),
        'status': payment.get_status_display(),
        'status_class': _payment_status_class(payment.status),
        'order_id': payment.order.id if payment.order else None,
        'description': f'Pago de orden #{payment.order.id}' if payment.order else 'Pago general',
        'is_positive': True,
        'object': payment,
        'created_by': payment.created_by,
    }


def _balance_history_item(balance_tx: Any) -> dict[str, Any]:
    positive_types = ['deposit', 'refund', 'transfer_in', 'adjustment']
    success_types = ['deposit', 'refund', 'transfer_in']
    return {
        'type': 'balance_transaction',
        'id': balance_tx.id,
        'date': balance_tx.created_at,
        'amount': balance_tx.amount,
        'method': balance_tx.get_transaction_type_display(),
        'status': 'Completado',
        'status_class': 'success' if balance_tx.transaction_type in success_types else 'info',
        'order_id': balance_tx.reference_order.id if balance_tx.reference_order else None,
        'description': balance_tx.notes or balance_tx.get_transaction_type_display(),
        'is_positive': balance_tx.transaction_type in positive_types,
        'object': balance_tx,
        'created_by': balance_tx.created_by,
    }


def _credit_history_item(credit_tx: Any) -> dict[str, Any]:
    positive_types = ['payment', 'adjustment', 'forgiveness', 'correction']
    charge_types = ['purchase', 'interest', 'fee']
    return {
        'type': 'credit_transaction',
        'id': credit_tx.id,
        'date': credit_tx.created_at,
        'amount': credit_tx.amount,
        'method': credit_tx.get_transaction_type_display(),
        'status': 'Completado',
        'status_class': 'warning' if credit_tx.transaction_type in charge_types else 'success',
        'order_id': credit_tx.reference_order.id if credit_tx.reference_order else None,
        'description': credit_tx.notes or credit_tx.get_transaction_type_display(),
        'is_positive': credit_tx.transaction_type in positive_types,
        'object': credit_tx,
        'created_by': credit_tx.created_by,
    }


def _build_payment_history(client: Client) -> List[dict[str, Any]]:
    payments = client.payments.select_related('order', 'created_by').order_by('-date')
    balance_transactions = client.balance_transactions.select_related(
        'reference_order',
        'reference_payment',
        'created_by',
    ).order_by('-created_at')
    credit_transactions = client.credit_transactions.select_related(
        'reference_order',
        'reference_payment',
        'created_by',
    ).order_by('-created_at')

    payment_history = []
    for payment in payments:
        payment_history.append(_payment_history_item(payment))

    for balance_tx in balance_transactions:
        if balance_tx.reference_payment:
            continue
        payment_history.append(_balance_history_item(balance_tx))

    for credit_tx in credit_transactions:
        if credit_tx.reference_payment:
            continue
        payment_history.append(_credit_history_item(credit_tx))

    payment_history.sort(key=lambda item: item['date'], reverse=True)
    return payment_history


def _parse_order_ids(request: HttpRequest) -> List[int]:
    raw_order_ids = (
        request.POST.getlist('orders')
        if request.method == 'POST'
        else request.GET.getlist('orders')
    )
    order_ids = []
    for raw_order_id in raw_order_ids:
        try:
            order_ids.append(int(raw_order_id))
        except (TypeError, ValueError):
            continue
    return order_ids


def _parse_payment_amount(raw_amount: str) -> Decimal:
    try:
        return Decimal(str(raw_amount))
    except (InvalidOperation, TypeError, ValueError):
        raise payment_services.ClientOrderPaymentError('El monto de pago es inválido.')


def _selected_order_payment_context(
    client: Client,
    selected_orders: List[Order],
    *,
    amount: Decimal | None = None,
    error_message: str | None = None,
) -> dict[str, Any]:
    for order in selected_orders:
        order.remaining_payment_amount = payment_services.get_unpaid_amount(order)

    selected_total = sum(
        (order.remaining_payment_amount for order in selected_orders),
        Decimal('0.00'),
    )
    payment_types = [
        (value, label)
        for value, label in PAYMENT_METHOD_CHOICES
        if value != 'pending_credit'
    ]
    return {
        'client': client,
        'selected_orders': selected_orders,
        'selected_total': selected_total,
        'payment_amount': amount if amount is not None else selected_total,
        'payment_types': payment_types,
        'error_message': error_message,
    }


@login_required
def pay_selected_orders(request: HttpRequest, pk: int) -> HttpResponse:
    client = get_object_or_404(Client, pk=pk)
    order_ids = _parse_order_ids(request)

    try:
        selected_orders = payment_services.get_selected_unpaid_orders(client, order_ids)
    except payment_services.ClientOrderPaymentError as exc:
        messages.error(request, str(exc))
        return redirect('clients:detail', pk=client.pk)

    if request.method == 'POST':
        submitted_amount = Decimal('0.00')
        try:
            submitted_amount = _parse_payment_amount(request.POST.get('amount', '0'))
            result = payment_services.pay_client_orders(
                client=client,
                orders=selected_orders,
                payment_method=request.POST.get('payment_method', 'cash'),
                amount=submitted_amount,
                request_user=request.user,
            )
        except (payment_services.ClientOrderPaymentError, ValueError) as exc:
            context = _selected_order_payment_context(
                client,
                selected_orders,
                amount=submitted_amount,
                error_message=str(exc),
            )
            return render(request, 'pay_selected_orders.html', context)

        messages.success(
            request,
            f'Se registró el pago de {len(result["orders"])} pedido(s) por ${result["selected_total"]:.2f}.',
        )
        if result['balance_added'] > 0:
            messages.info(
                request,
                f'Se agregó ${result["balance_added"]:.2f} al saldo del cliente.',
            )
        return redirect('clients:detail', pk=client.pk)

    context = _selected_order_payment_context(client, selected_orders)
    return render(request, 'pay_selected_orders.html', context)


@login_required
def detail(request, pk):
    client = get_object_or_404(Client, pk=pk)
    orders = client.orders.all().prefetch_related('items__product', 'payments').order_by('-created_at')
    payments = client.payments.all()
    all_payment_data = _build_payment_history(client)
    orders_page = _paginate_client_detail_items(request, orders, page_param='orders_page')
    payments_page = _paginate_client_detail_items(
        request,
        all_payment_data,
        page_param='payments_page',
    )
    client_invoices = _get_client_detail_invoices(client)
    
    # Calculate client statistics
    total_orders = orders.count()
    total_spent = payments.filter(status='completed').aggregate(total=Sum('amount'))['total'] or 0
    pending_orders = orders.filter(status='pending').count()
    completed_orders = orders.filter(status='completed').count()
    
    # Get client's contacts and addresses
    contacts = client.contacts.all()
    addresses = client.addresses.filter(active=True)
    branches = Client.objects.none()
    if client.type == 'corporate':
        branches = client.branches.all().order_by('name')
    billing_data = client.billing_info.effective.data

    # Get route information for the client
    route_clients = client.client_routes.filter(is_active=True).select_related(
        'route__transportation__assigned_driver__user',
        'route'
    ).order_by('sequence')
    
    # Get upcoming route client orders (specific deliveries)
    upcoming_route_orders = get_upcoming_route_orders(client, limit=10)
    
    # Get recent completed route orders for reference
    recent_completed_routes = get_recent_completed_route_orders(client, limit=5)
    billing_frequency = client.billing_info.effective.frequency
    billing_data = client.billing_info.effective.data
    # Get pending payment data
    from clients.services.pending_payment_service import get_overdue_orders_for_client
    pending_payment_data = get_overdue_orders_for_client(client)
    debt_percentage = int(client.current_debt / client.credit_limit * 100) if client.credit_limit > 0 else 0
    client_invoices_list = tuple(client_invoices)
    snapshot_context = build_client_detail_snapshot(
        client=client,
        billing_frequency=billing_frequency,
        route_clients=route_clients,
        upcoming_route_orders=upcoming_route_orders,
        client_invoices=client_invoices_list,
        pending_payment_data=pending_payment_data,
        debt_percentage=debt_percentage,
    )

    context = {
        'client': client,
        'orders': orders_page,
        'payments': payments_page,
        'all_payment_data': payments_page,
        'contacts': contacts,
        'addresses': addresses,
        'branches': branches,
        'billing_data': billing_data,
        'billing_frequency': billing_frequency,
        'route_clients': route_clients,
        'upcoming_route_orders': upcoming_route_orders,
        'recent_completed_routes': recent_completed_routes,
        'client_invoices': client_invoices_list,
        'debt_percentage': debt_percentage,
        'stats': {
            'total_orders': total_orders,
            'total_spent': total_spent,
            'pending_orders': pending_orders,
            'completed_orders': completed_orders,
        },
        'pending_payment_data': pending_payment_data,
        **snapshot_context,
    }
    
    return render(request, 'client_detail.html', context)


@login_required
def corporate_branches(request: HttpRequest, pk: int) -> HttpResponse:
    client = get_object_or_404(Client, pk=pk)
    if client.type != 'corporate':
        raise Http404('La vista de sucursales solo aplica a clientes corporativos.')

    context = build_corporate_branch_workspace(client, request.GET)
    return render(request, 'corporate_branch_workspace.html', context)


@login_required
def client_orders(request, client_pk):
    client = get_object_or_404(Client, pk=client_pk)
    orders = Order.objects.unbilled_for_client(client=client)
    orders_data = [
        {
            'id': order.id,
            'order_date': order.order_date.isoformat(),
            'total_amount': str(order.total_amount),
            'status': order.status,
        }
        for order in orders
    ]
    return JsonResponse({'orders': orders_data})

@login_required
def update_client(request, pk):
    """
    Update a client via PATCH request.
    Only accessible to users with 'change_client' permission.
    """
    import json
    from django.core.exceptions import ValidationError
    from django.contrib.auth.decorators import permission_required
    from clients.services.client_service import update_client as update_client_service, ClientUpdateData
    
    # Check permission
    if not request.user.has_perm('clients.change_client'):
        return JsonResponse(
            {'success': False, 'error': 'No tiene permiso para actualizar clientes'},
            status=403
        )
    
    # Only allow PATCH requests
    if request.method != 'PATCH':
        return JsonResponse(
            {'success': False, 'error': 'Método no permitido. Use PATCH'},
            status=405
        )
    
    client = get_object_or_404(Client, pk=pk)
    
    try:
        # Parse JSON body
        body_unicode = request.body.decode('utf-8')
        body = json.loads(body_unicode)
        
        # Create update data from request body
        update_data = ClientUpdateData(
            name=body.get('name'),
            active=body.get('active'),
            note=body.get('note'),
            type=body.get('type'),
            corporate_id=body.get('corporate_id'),
            credit_limit=body.get('credit_limit'),
            can_pay_with_credit=body.get('can_pay_with_credit'),
            address_link=body.get('address_link'),
            requires_billing=body.get('requires_billing'),
            credit_override_enabled=body.get('credit_override_enabled'),
        )
        
        # Update the client using the service
        updated_client = update_client_service(client, update_data, request.user)
        
        # Return success response with updated data
        return JsonResponse({
            'success': True,
            'message': 'Cliente actualizado exitosamente',
            'data': {
                'id': updated_client.pk,
                'name': updated_client.name,
                'requires_billing': updated_client.requires_billing,
                'active': updated_client.active,
                'can_pay_with_credit': updated_client.can_pay_with_credit,
                'credit_override_enabled': updated_client.credit_override_enabled,
            }
        })
    
    except json.JSONDecodeError:
        return JsonResponse(
            {'success': False, 'error': 'JSON inválido'},
            status=400
        )
    except ValidationError as e:
        return JsonResponse(
            {'success': False, 'error': str(e)},
            status=400
        )
    except ValueError as e:
        return JsonResponse(
            {'success': False, 'error': str(e)},
            status=400
        )
    except Exception as e:
        return JsonResponse(
            {'success': False, 'error': f'Error al actualizar cliente: {str(e)}'},
            status=500
        )

def get_clients(request):
    search_query = request.GET.get('search', '').strip()
    client_list_mode = request.GET.get('mode', '').strip()
    if client_list_mode not in {'outside_route_sales', 'credits'}:
        client_list_mode = ''
    
    # Start with all clients
    clients_queryset = Client.objects.select_related().prefetch_related(
        'contacts', 'addresses'
    ).order_by('-created_at', 'name')

    if client_list_mode == 'credits':
        clients_queryset = clients_queryset.filter(current_debt__gt=0)
    
    # Apply search filter if query exists
    if search_query:
        clients_queryset = clients_queryset.filter(
            Q(name__icontains=search_query) |
            Q(note__icontains=search_query) |
            Q(contacts__name__icontains=search_query) |
            Q(contacts__phone__icontains=search_query) |
            Q(contacts__email__icontains=search_query) |
            Q(addresses__street__icontains=search_query) |
            Q(addresses__municipality__icontains=search_query) |
            Q(addresses__state__icontains=search_query) |
            Q(invoice_data__rfc__icontains=search_query) |
            Q(invoice_data__razon_social__icontains=search_query)
        ).distinct()
    
    # Pagination
    paginator = Paginator(clients_queryset, 10)  # Show 10 clients per page
    page = request.GET.get('page')
    
    try:
        clients = paginator.page(page)
    except PageNotAnInteger:
        # If page is not an integer, deliver first page.
        clients = paginator.page(1)
    except EmptyPage:
        # If page is out of range (e.g. 9999), deliver last page of results.
        clients = paginator.page(paginator.num_pages)

    page_title = 'Clientes'
    page_subtitle = ''
    if client_list_mode == 'outside_route_sales':
        page_title = 'Ventas fuera de ruta'
        page_subtitle = 'Busca cualquier cliente para crear una venta manual.'
    elif client_list_mode == 'credits':
        page_title = 'Créditos'
        page_subtitle = 'Clientes con deuda pendiente para consulta o cobro.'

    preserved_query = {}
    if client_list_mode:
        preserved_query['mode'] = client_list_mode
    if search_query:
        preserved_query['search'] = search_query

    mode_query = urlencode({'mode': client_list_mode}) if client_list_mode else ''
    pagination_query = urlencode(preserved_query)
    clear_url = reverse('clients:list')
    if mode_query:
        clear_url = f'{clear_url}?{mode_query}'
    
    context = {
        'clients': clients,
        'search_query': search_query,
        'total_clients': paginator.count,
        'has_search': bool(search_query),
        'client_list_mode': client_list_mode,
        'page_title': page_title,
        'page_subtitle': page_subtitle,
        'mode_query': mode_query,
        'pagination_query': pagination_query,
        'client_list_clear_url': clear_url,
    }
    return context
@login_required
def pay_credit(request, pk):
    """View for paying credit (reducing debt) for a client"""
    client = get_object_or_404(Client, pk=pk)
    
    if request.method == 'POST':
        form = ManualCreditTransactionForm(request.POST)
        if form.is_valid():
            amount = form.cleaned_data['amount']
            transaction_type = form.cleaned_data['transaction_type']
            description = form.cleaned_data['description']
            notes = form.cleaned_data['notes']
            new_credit_limit = form.cleaned_data.get('new_credit_limit')
            
            try:
                from clients.services import balance_service

                if transaction_type == 'limit_change':
                    # Update credit limit
                    balance_service.update_credit_limit(
                        client=client,
                        new_limit=new_credit_limit,
                        user=request.user,
                        notes=f"{description}. {notes}"
                    )
                    messages.success(
                        request,
                        f"Límite de crédito actualizado exitosamente. {client.name} ahora tiene ${client.credit_limit:.2f} de límite."
                    )

                elif transaction_type in ['payment', 'forgiveness', 'adjustment', 'correction']:
                    # Pay down debt
                    paid_amount = balance_service.pay_debt(
                        client=client,
                        amount=amount,
                        transaction_type=transaction_type,
                        user=request.user,
                        notes=f"{description}. {notes}"
                    )
                    messages.success(
                        request,
                        f"Pago aplicado exitosamente. Deuda reducida en ${paid_amount:.2f}. {client.name} ahora debe ${client.current_debt:.2f}."
                    )

                elif transaction_type == 'payment_from_balance':
                    # Pay debt using client's balance
                    result = balance_service.pay_debt_from_balance(
                        client=client,
                        amount=amount,
                        user=request.user,
                        notes=f"{description}. {notes}"
                    )
                    if result['success']:
                        messages.success(
                            request,
                            f"Pago con saldo exitoso. ${result['amount_paid']:.2f} descontados del saldo. "
                            f"Saldo restante: ${result['remaining_balance']:.2f}. "
                            f"Deuda restante: ${result['remaining_debt']:.2f}."
                        )
                    else:
                        messages.error(request, f"Error en pago con saldo: {result['error']}")
                        return render(request, 'pay_credit.html', {
                            'form': form,
                            'client': client,
                        })
                
                return redirect('clients:detail', pk=client.pk)
                
            except Exception as e:
                messages.error(request, f"Error al procesar la transacción: {str(e)}")
    else:
        # Initialize form with the client pre-selected and default to 'payment'
        form = ManualCreditTransactionForm(initial={'client': client, 'transaction_type': 'payment'})
        # Make client field readonly by disabling it
        form.fields['client'].widget.attrs['disabled'] = True
        form.fields['client'].required = False
    
    context = {
        'form': form,
        'client': client,
    }
    
    return render(request, 'pay_credit.html', context)

@login_required
def create_admin(request):
    return render(request, 'admin/clients/create.html')

@login_required
def add_balance(request, pk):
    """View for manually adding balance to a client outside of Django admin"""
    client = get_object_or_404(Client, pk=pk)
    
    if request.method == 'POST':
        form = ManualBalanceTransactionForm(request.POST)
        if form.is_valid():
            amount = form.cleaned_data['amount']
            transaction_type = form.cleaned_data['transaction_type']
            notes = form.cleaned_data['notes']
            
            try:
                from clients.services import balance_service

                balance_service.add_balance(
                    client=client,
                    amount=amount,
                    transaction_type=transaction_type,
                    user=request.user,
                    notes=f"[MANUAL]. Transacción manual realizada por {request.user.username}. {notes}"
                )

                messages.success(
                    request,
                    f"Saldo actualizado exitosamente. {client.name} ahora tiene ${client.balance:.2f} de saldo."
                )
                
                if request.path.startswith('/administrador/'):
                    return redirect('admin_clients')
                return redirect('clients:detail', pk=client.pk)
                
            except Exception as e:
                messages.error(request, f"Error al procesar la transacción: {str(e)}")
    else:
        # Initialize form with the client pre-selected and default to 'deposit'
        form = ManualBalanceTransactionForm(initial={'client': client, 'transaction_type': 'deposit'})
        # Make client field readonly by disabling it
        form.fields['client'].widget.attrs['disabled'] = True
        form.fields['client'].required = False
    
    context = {
        'form': form,
        'client': client,
    }
    
    return render(request, 'add_balance.html', context)
