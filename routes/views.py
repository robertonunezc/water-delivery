from django.shortcuts import redirect, render, get_object_or_404
from django import forms as django_forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpResponseForbidden, JsonResponse
from django.core.paginator import Paginator
from django.forms import inlineformset_factory
from django.urls import reverse
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone
from datetime import date, datetime
from .models import Route, RouteClient, RouteClientOrder, TruckInventorySession
from .forms import (
    RouteClientInlineForm,
    RouteForm,
    TruckInventoryLineFormSet,
    TruckInventorySessionForm,
)
from .services import (
    get_driver_transportation,
    get_inventory_routes_for_user,
    get_or_create_inventory_session,
    get_route_detail_payload,
    sync_session_reported_sales,
    with_active_reminder_counts,
)
from route_confirmations.services import attach_confirmation_states
from core.models import Employee, Transport
from clients.models import Client


def _is_admin_user(user) -> bool:
    return user.is_authenticated and user.is_staff


def _apply_route_form_styles(route_form: RouteForm) -> RouteForm:
    for field in route_form.fields.values():
        widget = field.widget
        if isinstance(widget, django_forms.CheckboxInput):
            widget.attrs['class'] = 'pg-checkbox-input'
            continue

        default_class = 'pg-select' if isinstance(widget, django_forms.Select) else 'pg-input'
        existing_classes = widget.attrs.get('class', '')
        widget.attrs['class'] = f"{existing_classes} {default_class}".strip()

    return route_form


def _get_route_client_formset(*, data=None, instance=None):
    formset_cls = inlineformset_factory(
        Route,
        RouteClient,
        form=RouteClientInlineForm,
        extra=1,
        can_delete=True,
    )
    return formset_cls(data=data, instance=instance, prefix='route_clients')


def _apply_route_client_formset_styles(route_client_formset):
    forms_to_style = list(route_client_formset.forms) + [route_client_formset.empty_form]
    for route_client_form in forms_to_style:
        for field in route_client_form.fields.values():
            widget = field.widget
            if isinstance(widget, django_forms.CheckboxInput):
                existing_classes = widget.attrs.get('class', '')
                widget.attrs['class'] = f"{existing_classes} pg-checkbox-input".strip()
                continue

            default_class = 'pg-select' if isinstance(widget, django_forms.Select) else 'pg-input'
            existing_classes = widget.attrs.get('class', '')
            widget.attrs['class'] = f"{existing_classes} {default_class}".strip()

    return route_client_formset


def _build_route_admin_context(*, route=None, active_tab='basic', forms_override=None):
    forms_override = forms_override or {}

    default_route_form = RouteForm(
        instance=route,
        initial={
            'is_active': True,
            'weekday': 'monday',
        },
    )
    route_form = forms_override.get('route_form') or default_route_form
    route_form = _apply_route_form_styles(route_form)

    route_client_formset = forms_override.get('route_client_formset')
    if route is not None and route_client_formset is None:
        route_client_formset = _get_route_client_formset(instance=route)
    if route_client_formset is not None:
        route_client_formset = _apply_route_client_formset_styles(route_client_formset)

    return {
        'route': route,
        'active_tab': active_tab,
        'route_form': route_form,
        'route_client_formset': route_client_formset,
        'is_create': route is None,
    }


def _get_admin_routes_context(request):
    search_query = request.GET.get('search', '').strip()

    routes_queryset = (
        Route.objects.select_related('transportation')
        .annotate(
            active_clients_count=Count(
                'route_clients',
                filter=Q(route_clients__is_active=True),
            )
        )
        .order_by('-created_at', 'name')
    )

    if search_query:
        routes_queryset = routes_queryset.filter(
            Q(name__icontains=search_query)
            | Q(description__icontains=search_query)
            | Q(transportation__license_plate__icontains=search_query)
            | Q(transportation__model__icontains=search_query)
            | Q(weekday__icontains=search_query)
        )

    paginator = Paginator(routes_queryset, 10)
    routes = paginator.get_page(request.GET.get('page'))

    return {
        'routes': routes,
        'search_query': search_query,
        'has_search': bool(search_query),
        'total_routes': paginator.count,
        'active_routes_count': Route.objects.filter(is_active=True).count(),
    }


@user_passes_test(_is_admin_user)
def list_admin(request):
    context = _get_admin_routes_context(request)
    return render(request, 'admin/routes/list.html', context)


@user_passes_test(_is_admin_user)
def create_admin(request):
    active_tab = 'basic'

    if request.method == 'POST':
        route_form = RouteForm(request.POST)
        route_form = _apply_route_form_styles(route_form)
        if route_form.is_valid():
            route = route_form.save()
            messages.success(request, 'Ruta creada correctamente. Ahora puede asignar clientes.')
            return redirect(f"{reverse('admin_update_route', kwargs={'pk': route.pk})}?tab=clients")

        context = _build_route_admin_context(
            route=None,
            active_tab=active_tab,
            forms_override={'route_form': route_form},
        )
        return render(request, 'admin/routes/form.html', context)

    context = _build_route_admin_context(route=None, active_tab=active_tab)
    return render(request, 'admin/routes/form.html', context)


@user_passes_test(_is_admin_user)
def update_admin(request, pk):
    route = get_object_or_404(Route, pk=pk)
    active_tab = request.GET.get('tab', 'basic')

    if request.method == 'POST':
        section = request.POST.get('section', 'basic')
        active_tab = section

        if section == 'basic':
            route_form = RouteForm(request.POST, instance=route)
            route_form = _apply_route_form_styles(route_form)
            if route_form.is_valid():
                route_form.save()
                messages.success(request, 'Datos básicos de la ruta actualizados correctamente.')
                return redirect(f"{reverse('admin_update_route', kwargs={'pk': route.pk})}?tab=basic")

            context = _build_route_admin_context(
                route=route,
                active_tab='basic',
                forms_override={'route_form': route_form},
            )
            return render(request, 'admin/routes/form.html', context)

        if section == 'clients':
            route_client_formset = _get_route_client_formset(data=request.POST, instance=route)
            route_client_formset = _apply_route_client_formset_styles(route_client_formset)

            if route_client_formset.is_valid():
                route_client_formset.save()
                messages.success(request, 'Clientes de la ruta actualizados correctamente.')
                return redirect(f"{reverse('admin_update_route', kwargs={'pk': route.pk})}?tab=clients")

            context = _build_route_admin_context(
                route=route,
                active_tab='clients',
                forms_override={'route_client_formset': route_client_formset},
            )
            return render(request, 'admin/routes/form.html', context)

    context = _build_route_admin_context(route=route, active_tab=active_tab)
    return render(request, 'admin/routes/form.html', context)


def _parse_inventory_service_date(raw_date: str | None) -> date:
    if raw_date:
        try:
            return datetime.strptime(raw_date, '%Y-%m-%d').date()
        except ValueError:
            pass
    return timezone.localdate()


def _get_inventory_service_date(request) -> date:
    raw_date = request.POST.get('service_date') or request.GET.get('date')
    return _parse_inventory_service_date(raw_date)


def _get_posted_inventory_selection(request):
    service_date = _get_inventory_service_date(request)
    route = Route.objects.filter(pk=request.POST.get('route')).first()
    transportation = Transport.objects.filter(pk=request.POST.get('transportation')).first()
    return service_date, route, transportation


def _user_can_access_inventory_selection(
    user,
    route: Route | None,
    transportation: Transport | None,
    service_date: date,
) -> bool:
    if route is None or transportation is None:
        return False
    if route.transportation_id != transportation.pk:
        return False
    if user.is_staff:
        return True

    driver_transportation = get_driver_transportation(user)
    if driver_transportation is None or driver_transportation.pk != transportation.pk:
        return False

    return get_inventory_routes_for_user(user, service_date).filter(pk=route.pk).exists()


def _line_form_is_empty(cleaned_data: dict) -> bool:
    if cleaned_data.get('product') is None:
        return True
    counts = [
        cleaned_data.get('full_loaded') or 0,
        cleaned_data.get('full_returned') or 0,
        cleaned_data.get('empty_returned') or 0,
    ]
    return all(count == 0 for count in counts) and not cleaned_data.get('notes')


def _save_inventory_line_formset(formset) -> None:
    for line_form in formset.forms:
        cleaned_data = getattr(line_form, 'cleaned_data', None)
        if not cleaned_data:
            continue
        if cleaned_data.get('DELETE'):
            if line_form.instance.pk:
                line_form.instance.delete()
            continue
        if not line_form.instance.pk and _line_form_is_empty(cleaned_data):
            continue

        line = line_form.save(commit=False)
        line.session = formset.instance
        line.recalculate()
        line.save()


def _get_initial_inventory_session(user, service_date: date) -> TruckInventorySession | None:
    routes = get_inventory_routes_for_user(user, service_date)
    if user.is_staff:
        route = routes.filter(pk__isnull=False).first() if routes.count() == 1 else None
    else:
        route = routes.first() if routes.count() == 1 else None

    if route is None or route.transportation is None:
        return None
    return get_or_create_inventory_session(
        route=route,
        transportation=route.transportation,
        service_date=service_date,
        user=user,
    )


def _build_inventory_context(
    *,
    request,
    service_date: date,
    session: TruckInventorySession | None = None,
    session_form: TruckInventorySessionForm | None = None,
    line_formset=None,
) -> dict:
    routes = get_inventory_routes_for_user(request.user, service_date)
    session_form = session_form or TruckInventorySessionForm(
        user=request.user,
        service_date=service_date,
        instance=session,
        initial={'service_date': service_date},
    )
    line_formset = line_formset or TruckInventoryLineFormSet(
        instance=session,
        prefix='lines',
    )
    return {
        'service_date': service_date,
        'session': session,
        'session_form': session_form,
        'line_formset': line_formset,
        'has_available_routes': routes.exists(),
        'can_close': (
            session is not None
            and session.status == TruckInventorySession.Status.OPEN
        ),
    }


@login_required
def truck_inventory(request):
    """Single operational form for route truck inventory counts."""
    service_date = _get_inventory_service_date(request)

    if request.method == 'POST':
        posted_date, route, transportation = _get_posted_inventory_selection(request)
        if not _user_can_access_inventory_selection(
            request.user,
            route,
            transportation,
            posted_date,
        ):
            return HttpResponseForbidden('No tienes permiso para capturar este inventario.')

        session_form = TruckInventorySessionForm(
            request.POST,
            user=request.user,
            service_date=posted_date,
        )
        if session_form.is_valid():
            with transaction.atomic():
                session = get_or_create_inventory_session(
                    route=session_form.cleaned_data['route'],
                    transportation=session_form.cleaned_data['transportation'],
                    service_date=session_form.cleaned_data['service_date'],
                    user=request.user,
                )
                session.notes = session_form.cleaned_data.get('notes')
                session.save(update_fields=['notes', 'updated_at'])
                line_formset = TruckInventoryLineFormSet(
                    request.POST,
                    instance=session,
                    prefix='lines',
                )
                if line_formset.is_valid():
                    _save_inventory_line_formset(line_formset)
                    if request.POST.get('action') == 'close':
                        sync_session_reported_sales(session)
                        session.close(user=request.user)
                        messages.success(request, 'Inventario de camioneta cerrado correctamente.')
                    else:
                        messages.success(request, 'Inventario de camioneta guardado correctamente.')
                    return redirect('routes:truck_inventory')
        else:
            session = None
            line_formset = TruckInventoryLineFormSet(request.POST, prefix='lines')

        context = _build_inventory_context(
            request=request,
            service_date=posted_date,
            session=session if 'session' in locals() else None,
            session_form=session_form,
            line_formset=line_formset if 'line_formset' in locals() else None,
        )
        return render(request, 'routes/truck_inventory_form.html', context)

    session = _get_initial_inventory_session(request.user, service_date)
    context = _build_inventory_context(
        request=request,
        service_date=service_date,
        session=session,
    )
    return render(request, 'routes/truck_inventory_form.html', context)


@login_required
def routes_by_transportation_and_day(request):
    """List all routes filtered by transportation and/or day"""
    transportation_id = request.GET.get('transportation')
    weekday = request.GET.get('weekday')
    
    routes = Route.objects.filter(is_active=True).select_related('transportation')
    
    if transportation_id:
        routes = routes.filter(transportation_id=transportation_id)
    
    if weekday:
        routes = routes.filter(weekday=weekday)
    
    # Get all transportations for filter dropdown
    transportations = Transport.objects.filter(is_active=True)
    
    context = {
        'routes': routes,
        'transportations': transportations,
        'selected_transportation': transportation_id,
        'selected_weekday': weekday,
        'weekday_choices': Route._meta.get_field('weekday').choices,
    }
    
    return render(request, 'routes/routes_list.html', context)


@login_required
def today_route(request):
    """Show today's route for the logged-in employee"""
       
    if not hasattr(request.user, 'employee'):
        return redirect('routes:list')  # Redirect to a page explaining the issue
    
    employee = request.user.employee
    try:
        transportation = Transport.objects.get(assigned_driver=employee, is_active=True)
    except Transport.DoesNotExist:
        return render(request, 'routes/no_transportation.html', {
            'employee': employee
        })
    
    # Get today's route for this transportation
    today_routes = Route.get_today_routes(transportation=transportation)
    
    if not today_routes.exists():
        return render(request, 'routes/no_route_today.html', {
            'transportation': transportation,
            'employee': employee,
            'today': date.today()
        })
    
    # For now, assume one route per transportation per day
    today_route = today_routes.first()
    today = date.today()
    
    # Get today's scheduled client orders
    today_orders = RouteClientOrder.objects.filter(
        route=today_route,
        visit_date=today
    ).select_related('client', 'order').order_by('sequence')
    
    # Get regular clients for this route (for manual order creation)
    regular_clients = RouteClient.objects.due_on(today).filter(
        route=today_route
    ).select_related('client').order_by('sequence')
    regular_clients = with_active_reminder_counts(
        regular_clients,
        user=request.user,
        today=today,
    )
    regular_clients = attach_confirmation_states(
        list(regular_clients),
        today=today,
    )
    
    context = {
        'route': today_route,
        'transportation': transportation,
        'employee': employee,
        'today_orders': today_orders,
        'route_clients': regular_clients,
        'regular_clients': regular_clients,
        'today': today,
        'is_today_view': True,
    }
    
    return render(request, 'routes/route_detail.html', context)


@login_required
def route_detail(request, route_id):
    """Detailed view of a specific route"""
    route = get_object_or_404(Route, id=route_id, is_active=True)
    search_query = request.GET.get('q', '').strip()
    payload = get_route_detail_payload(
        route=route,
        search_query=search_query,
        user=request.user,
    )
    
    context = {
        'route': route,
        'route_clients': payload.route_clients,
        'recent_orders': payload.recent_orders,
        'today': payload.today,
        'is_today_view': payload.is_today_view,
        'search_query': payload.search_query,
    }
    
    return render(request, 'routes/route_detail.html', context)


@login_required
def route_orders_by_date(request, route_id):
    """Get orders for a specific route and date"""
    route = get_object_or_404(Route, id=route_id, is_active=True)
    date_str = request.GET.get('date', date.today().isoformat())
    
    try:
        visit_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        visit_date = date.today()
    
    route_orders = RouteClientOrder.objects.filter(
        route=route,
        visit_date=visit_date
    ).select_related('client', 'order').order_by('sequence')
    
    context = {
        'route': route,
        'route_orders': route_orders,
        'visit_date': visit_date,
    }
    
    return render(request, 'routes/route_orders_by_date.html', context)


@login_required
def mark_order_completed(request, route_order_id):
    """Mark a route client order as completed"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    route_order = get_object_or_404(RouteClientOrder, id=route_order_id)
    
    # Check if user has permission (driver of the assigned transportation or admin)
    try:
        employee = request.user.employee
        if employee.position == 'driver':
            transportation = Transport.objects.filter(assigned_driver=employee).first()
            if not transportation or route_order.route.transportation != transportation:
                return JsonResponse({'error': 'Access denied'}, status=403)
    except Employee.DoesNotExist:
        if not request.user.is_staff:
            return JsonResponse({'error': 'Access denied'}, status=403)
    
    route_order.mark_completed()
    
    return JsonResponse({
        'success': True,
        'completed_at': route_order.completed_at.isoformat() if route_order.completed_at else None
    })


@login_required
def routes_api_json(request):
    """API endpoint to get routes as JSON"""
    transportation_id = request.GET.get('transportation')
    weekday = request.GET.get('weekday')
    
    routes = Route.objects.filter(is_active=True).select_related('transportation')
    
    if transportation_id:
        routes = routes.filter(transportation_id=transportation_id)
    
    if weekday:
        routes = routes.filter(weekday=weekday)
    
    routes_data = []
    for route in routes:
        routes_data.append({
            'id': route.id,
            'name': route.name,
            'description': route.description,
            'transportation': {
                'id': route.transportation.id,
                'license_plate': route.transportation.license_plate,
                'model': route.transportation.model,
            },
            'weekday': route.weekday,
            'weekday_display': route.get_weekday_display(),
            'client_count': route.route_clients.filter(is_active=True).count(),
        })
    
    return JsonResponse({
        'routes': routes_data,
        'total': len(routes_data)
    })


@staff_member_required
def check_client_assignments(request):
    """AJAX endpoint for route assignment eligibility."""
    client_id = request.GET.get('client_id')
    
    if not client_id:
        return JsonResponse({'error': 'Client ID is required'}, status=400)
    
    try:
        client = Client.objects.get(id=client_id)
    except Client.DoesNotExist:
        return JsonResponse({'error': 'Client not found'}, status=404)
    
    return JsonResponse({
        'has_conflicts': False,
        'existing_routes': [],
        'client_name': client.name,
        'message': f"Cliente '{client.name}' puede asignarse a múltiples rutas."
    })
