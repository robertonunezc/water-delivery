from datetime import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from routes.models import Route, RouteClient

from .forms import ConfirmationOverrideForm
from .models import VisitConfirmation
from .services import (
    format_visit_date,
    override_confirmation,
    record_public_response,
    send_visit_confirmation,
)


def _is_staff_user(user) -> bool:
    return user.is_authenticated and user.is_staff


@login_required
def list_confirmations(request):
    confirmations_queryset = (
        VisitConfirmation.objects.select_related(
            'route_client__route',
            'route_client__client',
            'sent_by',
            'responded_by',
        )
        .order_by('-visit_date', '-created_at')
    )
    search_query = request.GET.get('search', '').strip()
    route_id = request.GET.get('route', '').strip()
    status_filter = request.GET.get('status', '').strip()
    visit_date_filter = request.GET.get('visit_date', '').strip()

    if search_query:
        confirmations_queryset = confirmations_queryset.filter(
            Q(route_client__client__name__icontains=search_query)
            | Q(route_client__route__name__icontains=search_query)
        )

    if route_id:
        confirmations_queryset = confirmations_queryset.filter(route_client__route_id=route_id)

    if visit_date_filter:
        try:
            parsed_date = datetime.strptime(visit_date_filter, '%Y-%m-%d').date()
            confirmations_queryset = confirmations_queryset.filter(visit_date=parsed_date)
        except ValueError:
            messages.warning(request, 'La fecha de visita no es válida.')

    if status_filter:
        confirmations_queryset = _filter_by_display_status(
            confirmations_queryset,
            status_filter,
        )

    paginator = Paginator(confirmations_queryset, 20)
    confirmations = paginator.get_page(request.GET.get('page'))

    return render(
        request,
        'route_confirmations/list.html',
        {
            'confirmations': confirmations,
            'routes': Route.objects.filter(is_active=True).order_by('name'),
            'statuses': ['Enviada', 'Expirada', 'Confirmada', 'NO visitar'],
            'search_query': search_query,
            'selected_route': route_id,
            'selected_status': status_filter,
            'visit_date_filter': visit_date_filter,
            'override_form': ConfirmationOverrideForm(),
        },
    )


@login_required
@require_POST
def send_confirmation(request, route_client_id: int):
    route_client = get_object_or_404(
        RouteClient.objects.select_related('route', 'client'),
        pk=route_client_id,
    )
    result = send_visit_confirmation(route_client, sent_by=request.user, request=request)
    if result.success:
        messages.success(request, f'Confirmación enviada a {len(result.receipts)} contacto(s).')
        for warning in result.warning_messages:
            messages.warning(request, f'No se pudo enviar a {warning}')
    elif result.outcome == 'no_recipients':
        messages.warning(request, 'El cliente no tiene contactos con correo electrónico.')
    elif result.outcome == 'pending':
        messages.info(request, 'La confirmación ya fue enviada y todavía no expira.')
    elif result.outcome == 'final':
        messages.info(request, 'La visita ya tiene una respuesta final.')
    else:
        messages.error(request, 'No se pudo enviar la confirmación.')

    return redirect(request.POST.get('next') or reverse('routes:detail', kwargs={'route_id': route_client.route_id}))


@user_passes_test(_is_staff_user)
@require_POST
def override_confirmation_status(request, pk: int):
    confirmation = get_object_or_404(VisitConfirmation, pk=pk)
    form = ConfirmationOverrideForm(request.POST)
    if form.is_valid():
        override_confirmation(
            confirmation,
            form.cleaned_data['status'],
            form.cleaned_data['note'],
            request.user,
        )
        messages.success(request, 'Confirmación ajustada correctamente.')
    else:
        messages.error(request, 'No se pudo ajustar la confirmación. Revisa la nota y el estatus.')

    return redirect(request.POST.get('next') or reverse('route_confirmations:list'))


def respond_to_confirmation(request, token: str, action: str):
    result = record_public_response(token, action)
    confirmation = result.confirmation
    context = {
        'outcome': result.outcome,
        'confirmation': confirmation,
        'client_name': confirmation.route_client.client.name if confirmation else '',
        'visit_date': format_visit_date(confirmation.visit_date) if confirmation else '',
        'decision': confirmation.display_status() if confirmation else '',
        'expired_message': 'Este enlace expiró. Por favor comunícate con nosotros para confirmar tu visita.',
    }
    return render(request, 'route_confirmations/confirmation_result.html', context)


def _filter_by_display_status(queryset, status_filter: str):
    from django.utils import timezone

    if status_filter == 'Expirada':
        return queryset.filter(
            status=VisitConfirmation.Status.SENT,
            expires_at__lt=timezone.now(),
        )
    if status_filter == 'Enviada':
        return queryset.filter(status=VisitConfirmation.Status.SENT).filter(
            Q(expires_at__isnull=True) | Q(expires_at__gte=timezone.now())
        )
    if status_filter in VisitConfirmation.Status.values:
        return queryset.filter(status=status_filter)
    return queryset
