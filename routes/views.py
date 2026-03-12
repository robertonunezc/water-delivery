from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.http import JsonResponse
from django.core.paginator import Paginator
from django.db.models import Q, Count, Prefetch
from django.utils import timezone
from datetime import date, datetime, timedelta
from .models import Route, RouteClient, RouteClientOrder
from core.models import Employee, Transport
from clients.models import Client
from orders.models import Order


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

    employee = request.user.employee

    # Get the transportation assigned to this driver
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
    
    # Get today's scheduled client orders
    today_orders = RouteClientOrder.objects.filter(
        route=today_route,
        visit_date=date.today()
    ).select_related('client', 'order').order_by('sequence')
    
    # Get regular clients for this route (for manual order creation)
    regular_clients = RouteClient.objects.due_on(date.today()).filter(
        route=today_route
    ).select_related('client').order_by('sequence')
    
    context = {
        'route': today_route,
        'transportation': transportation,
        'employee': employee,
        'today_orders': today_orders,
        'route_clients': regular_clients,
        'regular_clients': regular_clients,
        'today': date.today(),
        'is_today_view': True,
    }
    
    return render(request, 'routes/route_detail.html', context)


@login_required
def route_detail(request, route_id):
    """Detailed view of a specific route"""
    route = get_object_or_404(Route, id=route_id, is_active=True)
    
    # Get regular clients in this route with prefetched related data
    route_clients = RouteClient.objects.filter(
        route=route,
        is_active=True
    ).select_related('client').prefetch_related(
        'client__addresses',
        'client__contacts',
        'client__product_prices__product',
        Prefetch('client__orders',
                 queryset=Order.objects.select_related().prefetch_related('items__product').order_by('-created_at'),
                 to_attr='recent_orders')
    ).order_by('sequence')
    
    # Get recent client orders for this route
    recent_orders = RouteClientOrder.objects.filter(
        route=route,
        visit_date__gte=date.today() - timedelta(days=7)
    ).select_related('client', 'order').order_by('-visit_date', 'sequence')
    
    context = {
        'route': route,
        'route_clients': route_clients,
        'recent_orders': recent_orders,
        'today': date.today(),
        'is_today_view': False,
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
    """AJAX endpoint to check if a client is already assigned to other routes"""
    client_id = request.GET.get('client_id')
    current_route_id = request.GET.get('current_route_id')
    current_assignment_id = request.GET.get('current_assignment_id')
    
    if not client_id:
        return JsonResponse({'error': 'Client ID is required'}, status=400)
    
    try:
        client = Client.objects.get(id=client_id)
    except Client.DoesNotExist:
        return JsonResponse({'error': 'Client not found'}, status=404)
    
    # Find existing active assignments for this client
    existing_assignments = RouteClient.objects.filter(
        client=client,
        is_active=True
    ).select_related('route')
    
    # Exclude current assignment if editing
    if current_assignment_id:
        existing_assignments = existing_assignments.exclude(id=current_assignment_id)
    
    # Exclude current route if adding to a route
    if current_route_id:
        existing_assignments = existing_assignments.exclude(route_id=current_route_id)
    
    if existing_assignments.exists():
        # Build list of existing routes
        existing_routes = []
        for assignment in existing_assignments:
            route_info = f"{assignment.route.name} ({assignment.route.get_weekday_display()})"
            existing_routes.append(route_info)
        
        return JsonResponse({
            'has_conflicts': True,
            'existing_routes': existing_routes,
            'client_name': client.name,
            'message': f"Cliente '{client.name}' ya está asignado a otras rutas."
        })
    
    return JsonResponse({
        'has_conflicts': False,
        'client_name': client.name,
        'message': f"Cliente '{client.name}' no tiene conflictos de asignación."
    })
