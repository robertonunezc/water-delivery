from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.core.paginator import Paginator
from django.db.models import Q, Count, Prefetch
from .models import Route, RouteEmployee, RouteClient
from core.models import Employee
from clients.models import Client


@login_required
def employee_routes_list(request):
    """List all routes assigned to the current employee"""
    try:
        employee = request.user.employee
    except Employee.DoesNotExist:
        # If user is not an employee, show all routes (for admin)
        employee = None
    
    if employee:
        # Get routes for this specific employee
        routes = Route.objects.filter(
            route_employees__employee=employee,
            route_employees__status='active'
        ).prefetch_related(
            Prefetch(
                'route_clients',
                queryset=RouteClient.objects.select_related('client').order_by('sequence')
            ),
            'route_employees__employee__user'
        ).distinct()
    else:
        # Show all routes for admin users
        routes = Route.objects.all().prefetch_related(
            Prefetch(
                'route_clients',
                queryset=RouteClient.objects.select_related('client').order_by('sequence')
            ),
            'route_employees__employee__user'
        )
    
    # Add search functionality
    search_query = request.GET.get('search', '').strip()
    if search_query:
        routes = routes.filter(
            Q(name__icontains=search_query) |
            Q(description__icontains=search_query) |
            Q(route_clients__client__name__icontains=search_query)
        ).distinct()
    
    # Pagination
    paginator = Paginator(routes, 10)
    page_number = request.GET.get('page', 1)
    routes_page = paginator.get_page(page_number)
    
    context = {
        'routes': routes_page,
        'search_query': search_query,
        'has_search': bool(search_query),
        'total_routes': paginator.count,
        'employee': employee,
    }
    
    return render(request, 'routes/employee_routes_list.html', context)


@login_required
def route_detail(request, route_id):
    """Detailed view of a specific route with all clients"""
    route = get_object_or_404(Route, id=route_id)
    
    # Check if user has access to this route
    try:
        employee = request.user.employee
        if not route.route_employees.filter(employee=employee, status='active').exists():
            # If not assigned to this route and not admin, redirect
            if not request.user.is_staff:
                return render(request, 'routes/access_denied.html')
    except Employee.DoesNotExist:
        # Non-employee users (admin) can access all routes
        employee = None
    
    # Get clients in this route ordered by sequence
    route_clients = RouteClient.objects.filter(route=route).select_related(
        'client'
    ).prefetch_related(
        'client__contacts',
        'client__addresses'
    ).order_by('sequence')
    
    # Filter by day if specified
    day_filter = request.GET.get('day', '')
    if day_filter:
        route_clients = route_clients.filter(day_to_visit=day_filter)
    
    # Get unique days in this route
    days_in_route = RouteClient.objects.filter(route=route).values_list(
        'day_to_visit', flat=True
    ).distinct().order_by('day_to_visit')
    
    context = {
        'route': route,
        'route_clients': route_clients,
        'day_filter': day_filter,
        'days_in_route': days_in_route,
        'employee': employee,
    }
    
    return render(request, 'routes/route_detail.html', context)


@login_required
def route_clients_json(request, route_id):
    """API endpoint to get route clients as JSON for dynamic loading"""
    route = get_object_or_404(Route, id=route_id)
    
    # Check access permissions
    try:
        employee = request.user.employee
        if not route.route_employees.filter(employee=employee, status='active').exists():
            if not request.user.is_staff:
                return JsonResponse({'error': 'Access denied'}, status=403)
    except Employee.DoesNotExist:
        pass
    
    day_filter = request.GET.get('day', '')
    route_clients = RouteClient.objects.filter(route=route).select_related('client')
    
    if day_filter:
        route_clients = route_clients.filter(day_to_visit=day_filter)
    
    route_clients = route_clients.order_by('sequence')
    
    clients_data = []
    for route_client in route_clients:
        client = route_client.client
        clients_data.append({
            'id': client.id,
            'name': client.name,
            'sequence': route_client.sequence,
            'day_to_visit': route_client.get_day_to_visit_display(),
            'frecuency': route_client.get_frecuency_display(),
            'note': route_client.note or '',
            'active': client.active,
            'type': client.get_type_display(),
            'create_order_url': f'/orders/create/{client.id}/',
        })
    
    return JsonResponse({
        'route': {
            'id': route.id,
            'name': route.name,
            'description': route.description,
        },
        'clients': clients_data,
        'total': len(clients_data)
    })
