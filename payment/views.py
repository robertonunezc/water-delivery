from decimal import Decimal
import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q, Sum
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods

from clients.models import BalanceTransaction
from orders.models import Order
from payment import reversal_service, services
from payment.models import (
    PAYMENT_ENTRY_KIND_CHOICES,
    PAYMENT_ENTRY_KIND_PAYMENT,
    PAYMENT_ENTRY_KIND_REVERSAL,
    PAYMENT_METHOD_CHOICES,
    Payment,
    PaymentQuerySet,
)
from payment.services import PaymentRequestData


def _safe_next_url(request: HttpRequest, fallback: str) -> str:
    candidate = request.POST.get('next') or request.GET.get('next') or ''
    if candidate and url_has_allowed_host_and_scheme(candidate, allowed_hosts={request.get_host()}):
        return candidate
    return fallback


def _filter_payments_queryset(request: HttpRequest):
    qs = (
        Payment.objects.financial_events()
        .select_related('order', 'order__client', 'client', 'created_by', 'reversal_of', 'reversal_entry')
        .order_by('-date', '-id')
    )
    order_id = (request.GET.get('order_id') or '').strip()
    if order_id.isdigit():
        qs = qs.filter(order_id=int(order_id))

    client_query = (request.GET.get('client') or '').strip()
    if client_query:
        qs = qs.filter(
            Q(client__name__icontains=client_query)
            | Q(order__client__name__icontains=client_query)
        )

    date_from = (request.GET.get('date_from') or '').strip()
    if date_from:
        qs = qs.filter(date__date__gte=date_from)

    date_to = (request.GET.get('date_to') or '').strip()
    if date_to:
        qs = qs.filter(date__date__lte=date_to)

    method = (request.GET.get('method') or '').strip()
    if method:
        qs = qs.filter(method=method)

    entry_kind = (request.GET.get('entry_kind') or '').strip()
    if entry_kind in (PAYMENT_ENTRY_KIND_PAYMENT, PAYMENT_ENTRY_KIND_REVERSAL):
        qs = qs.filter(entry_kind=entry_kind)

    reversal_state = (request.GET.get('reversal_state') or '').strip()
    if reversal_state == 'active':
        qs = qs.reversible_receipts()
    elif reversal_state == 'reversed':
        qs = qs.effective_receipts().filter(reversal_entry__isnull=False)
    elif reversal_state == 'reversal':
        qs = qs.reversals()

    return qs


def _filter_standalone_deposits(request: HttpRequest):
    qs = (
        BalanceTransaction.objects.standalone_deposits()
        .select_related('client', 'created_by', 'reversal_transaction')
        .order_by('-created_at', '-id')
    )
    client_query = (request.GET.get('client') or '').strip()
    if client_query:
        qs = qs.filter(client__name__icontains=client_query)
    date_from = (request.GET.get('date_from') or '').strip()
    if date_from:
        qs = qs.filter(created_at__date__gte=date_from)
    date_to = (request.GET.get('date_to') or '').strip()
    if date_to:
        qs = qs.filter(created_at__date__lte=date_to)
    reversal_state = (request.GET.get('reversal_state') or '').strip()
    if reversal_state == 'active':
        qs = qs.filter(reversal_transaction__isnull=True)
    elif reversal_state == 'reversed':
        qs = qs.filter(reversal_transaction__isnull=False)
    return qs


@login_required
@require_http_methods(["GET"])
def payment_list_view(request: HttpRequest) -> HttpResponse:
    """Standalone manager/admin payments & standalone deposits history page."""
    reversal_service.require_payment_manager(request.user)
    active_tab = request.GET.get('tab') or 'payments'
    if active_tab not in ('payments', 'deposits'):
        active_tab = 'payments'

    context: dict = {
        'active_tab': active_tab,
        'method_choices': [m for m in PAYMENT_METHOD_CHOICES if m[0] != 'pending_credit'],
        'entry_kind_choices': PAYMENT_ENTRY_KIND_CHOICES,
        'filters': {
            'order_id': request.GET.get('order_id', ''),
            'client': request.GET.get('client', ''),
            'date_from': request.GET.get('date_from', ''),
            'date_to': request.GET.get('date_to', ''),
            'method': request.GET.get('method', ''),
            'entry_kind': request.GET.get('entry_kind', ''),
            'reversal_state': request.GET.get('reversal_state', ''),
        },
    }

    if active_tab == 'deposits':
        deposits_qs = _filter_standalone_deposits(request)
        paginator = Paginator(deposits_qs, 25)
        context['deposits_page'] = paginator.get_page(request.GET.get('page'))
        context['deposit_total'] = deposits_qs.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    else:
        payments_qs = _filter_payments_queryset(request)
        summary_net = payments_qs.aggregate(
            net_total=Sum(PaymentQuerySet.signed_amount_expression())
        )['net_total'] or Decimal('0.00')
        paginator = Paginator(payments_qs, 25)
        context['payments_page'] = paginator.get_page(request.GET.get('page'))
        context['net_total'] = summary_net
        context['receipt_count'] = payments_qs.effective_receipts().count()
        context['reversal_count'] = payments_qs.reversals().count()

    return render(request, 'payment/payment_list.html', context)


@login_required
@require_http_methods(["GET"])
def order_payments_view(request: HttpRequest, order_id: int) -> HttpResponse:
    """Order-scoped chronological payment and reversal history for managers/admins."""
    reversal_service.require_payment_manager(request.user)
    order = get_object_or_404(
        Order.objects.select_related('client', 'credit_account'),
        pk=order_id,
    )
    events = (
        order.payments.select_related('client', 'created_by', 'reversal_of', 'reversal_entry')
        .order_by('date', 'id')
    )
    order_total = Decimal(str(order.total_amount))
    net_paid = Decimal(str(order.total_paid))
    total_unpaid = max(order_total - net_paid, Decimal('0.00'))
    outstanding_credit = services.get_order_outstanding_credit(order)
    back_url = _safe_next_url(request, reverse('payment:list_payments'))

    return render(
        request,
        'payment/order_payments.html',
        {
            'order': order,
            'events': events,
            'order_total': order_total,
            'net_paid': net_paid,
            'total_unpaid': total_unpaid,
            'outstanding_credit': outstanding_credit,
            'back_url': back_url,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def reverse_payment_view(request: HttpRequest, payment_id: int) -> HttpResponse:
    """Preview (GET) and atomically confirm (POST) a single order payment reversal."""
    reversal_service.require_payment_manager(request.user)
    payment = get_object_or_404(Payment.objects.select_related('order'), pk=payment_id)
    default_next = reverse('payment:order_payments', args=[payment.order_id])
    next_url = _safe_next_url(request, default_next)
    reason = ''

    if request.method == 'POST':
        reason = (request.POST.get('reason') or '').strip()
        token = request.POST.get('preview_token')
        try:
            reversal = reversal_service.execute_payment_reversal(
                payment_id=payment.pk,
                user=request.user,
                reason=reason,
                preview_token=token,
                require_token=True,
            )
            messages.success(
                request,
                f'Pago #{payment.pk} revertido exitosamente (reversión #{reversal.pk}).',
            )
            return redirect(next_url)
        except reversal_service.StaleReversalPreviewError as exc:
            messages.warning(request, str(exc))
            plan = exc.plan
        except reversal_service.ReversalBlockedError as exc:
            messages.error(request, str(exc))
            plan = exc.plan
        except reversal_service.ReversalError as exc:
            messages.error(request, str(exc))
            plan = reversal_service.plan_payment_reversal(payment.pk)
    else:
        plan = reversal_service.plan_payment_reversal(payment.pk)

    preview_token = reversal_service.sign_reversal_token('payment', payment.pk, plan.fingerprint)
    return render(
        request,
        'payment/reverse_payment_preview.html',
        {
            'plan': plan,
            'preview_token': preview_token,
            'reason': reason,
            'next_url': next_url,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def reverse_deposit_view(request: HttpRequest, transaction_id: int) -> HttpResponse:
    """Preview (GET) and atomically confirm (POST) a standalone balance deposit reversal."""
    reversal_service.require_payment_manager(request.user)
    deposit_tx = get_object_or_404(BalanceTransaction, pk=transaction_id)
    default_next = f"{reverse('payment:list_payments')}?tab=deposits"
    next_url = _safe_next_url(request, default_next)
    reason = ''

    if request.method == 'POST':
        reason = (request.POST.get('reason') or '').strip()
        token = request.POST.get('preview_token')
        try:
            reversal_tx = reversal_service.execute_balance_deposit_reversal(
                transaction_id=deposit_tx.pk,
                user=request.user,
                reason=reason,
                preview_token=token,
                require_token=True,
            )
            messages.success(
                request,
                f'Abono a saldo #{deposit_tx.pk} revertido exitosamente (movimiento #{reversal_tx.pk}).',
            )
            return redirect(next_url)
        except reversal_service.StaleReversalPreviewError as exc:
            messages.warning(request, str(exc))
            plan = exc.plan
        except reversal_service.ReversalBlockedError as exc:
            messages.error(request, str(exc))
            plan = exc.plan
        except reversal_service.ReversalError as exc:
            messages.error(request, str(exc))
            plan = reversal_service.plan_balance_deposit_reversal(deposit_tx.pk)
    else:
        plan = reversal_service.plan_balance_deposit_reversal(deposit_tx.pk)

    preview_token = reversal_service.sign_reversal_token('deposit', deposit_tx.pk, plan.fingerprint)
    return render(
        request,
        'payment/reverse_deposit_preview.html',
        {
            'plan': plan,
            'preview_token': preview_token,
            'reason': reason,
            'next_url': next_url,
        },
    )


@login_required
@require_http_methods(["POST"])
@transaction.atomic
def create_payment(request):
    """
    Create payment(s) for an order.
    
    Supports two formats:
    1. Single payment (backward compatible):
       { order_id, payment_method, amount, credit_note?, cantidad_cobrada?, order_date?, payment_date? }
    
    2. Multiple payments (new format - balance first):
       { order_id, payments: [{amount, payment_method, credit_note?}, ...], cantidad_cobrada?, order_date?, payment_date? }
    """
    try:
        data = json.loads(request.body.decode('utf-8') or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    order_id = data.get('order_id')
    if not order_id:
        return JsonResponse({'error': 'Missing order_id'}, status=400)
    try:
        order = get_object_or_404(Order, pk=order_id)
        request_data = PaymentRequestData(
            payments_data=data.get('payments'),
            payment_method=data.get('payment_method'),
            cantidad_cobrada=data.get('cantidad_cobrada'),
            amount=data.get('amount'),
            credit_note=data.get('credit_note'),
            order_type=data.get('order_type'),
            notes=data.get('notes'),
            order_date=data.get('order_date'),
            payment_date=data.get('payment_date'),
        )
        response_data, status_code = services.process_payment_request(
            order=order,
            data=request_data,
            request_user=request.user,
        )
        return JsonResponse(response_data, status=status_code)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)
