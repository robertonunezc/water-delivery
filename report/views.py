from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.db.models import Q, Max, Min, Sum, Avg, Subquery, OuterRef, Count
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.utils import timezone
from datetime import datetime, timedelta
from decimal import Decimal
from django.contrib.auth.models import User
from clients.models import Client, CreditTransaction
from orders.models import Order, ORDER_STATUS_CHOICES
from payment.models import PAYMENT_METHOD_CHOICES


@login_required
def client_debt_report(request):
    """
    Report showing all clients with debt, including filters for debt range
    and the last debt payment date from CreditTransaction
    """
    # Get filter parameters from request
    search_query = request.GET.get('search', '').strip()
    min_debt = request.GET.get('min_debt', '').strip()
    max_debt = request.GET.get('max_debt', '').strip()
    
    # Start with clients that have debt
    clients_queryset = Client.objects.filter(
        current_debt__gt=0, 
        active=True
    ).select_related().prefetch_related(
        'contacts', 'addresses'
    )
    
    # Apply search filter if query exists
    if search_query:
        clients_queryset = clients_queryset.filter(
            Q(name__icontains=search_query) |
            Q(note__icontains=search_query) |
            Q(contacts__name__icontains=search_query) |
            Q(contacts__phone__icontains=search_query) |
            Q(contacts__email__icontains=search_query)
        ).distinct()
    
    # Apply debt range filters
    if min_debt:
        try:
            min_debt_value = Decimal(min_debt)
            clients_queryset = clients_queryset.filter(current_debt__gte=min_debt_value)
        except (ValueError, TypeError):
            min_debt = ''  # Clear invalid input
    
    if max_debt:
        try:
            max_debt_value = Decimal(max_debt)
            clients_queryset = clients_queryset.filter(current_debt__lte=max_debt_value)
        except (ValueError, TypeError):
            max_debt = ''  # Clear invalid input
    
    # Annotate with last payment information from CreditTransaction
    last_payment_subquery = CreditTransaction.objects.filter(
        client=OuterRef('pk'),
        transaction_type='payment'
    ).order_by('-created_at').values('created_at', 'amount')[:1]
    
    clients_queryset = clients_queryset.annotate(
        last_payment_date=Subquery(last_payment_subquery.values('created_at')),
        last_payment_amount=Subquery(last_payment_subquery.values('amount'))
    ).order_by('-current_debt', 'name')
    
    # Calculate summary statistics
    debt_stats = clients_queryset.aggregate(
        total_debt=Sum('current_debt'),
        avg_debt=Avg('current_debt'),
        min_debt_stat=Min('current_debt'),
        max_debt_stat=Max('current_debt')
    )
    
    # Pagination
    paginator = Paginator(clients_queryset, 15)  # Show 15 clients per page
    page = request.GET.get('page')
    
    try:
        clients = paginator.page(page)
    except PageNotAnInteger:
        clients = paginator.page(1)
    except EmptyPage:
        clients = paginator.page(paginator.num_pages)
    
    context = {
        'clients': clients,
        'search_query': search_query,
        'min_debt': min_debt,
        'max_debt': max_debt,
        'total_clients': paginator.count,
        'has_search': bool(search_query),
        'has_filters': bool(min_debt or max_debt),
        'debt_stats': debt_stats,
    }
    
    return render(request, 'report/client_debt_report.html', context)


@login_required
def orders_report(request):
    """
    Comprehensive orders report with multiple filters:
    - Search by client name, order ID, or notes
    - Filter by order status
    - Filter by date range (today, this week, this month, custom)
    - Filter by employee/owner
    - Filter by amount range
    - Sort options
    """
    owner = request.user
    # Get filter parameters from request
    search_query = request.GET.get('search', '').strip()
    status_filter = request.GET.get('status', '').strip()
    date_filter = request.GET.get('date_filter', '').strip()
    start_date = request.GET.get('start_date', '').strip()
    end_date = request.GET.get('end_date', '').strip()
    employee_filter = request.GET.get('employee', '').strip()
    min_amount = request.GET.get('min_amount', '').strip()
    max_amount = request.GET.get('max_amount', '').strip()
    sort_by = request.GET.get('sort_by', '-order_date').strip()
    
    # Start with all orders
    orders_queryset = Order.objects.select_related(
        'client', 'owner',
    ).prefetch_related(
        'items__product', 'client__contacts', 'payments'
    )
    
    # Apply search filter
    if search_query:
        orders_queryset = orders_queryset.filter(
            Q(client__name__icontains=search_query) |
            Q(id__icontains=search_query) |
            Q(notes__icontains=search_query) |
            Q(client__contacts__name__icontains=search_query)
        ).distinct()
    
    #Apply payment method filter
    payment_method = request.GET.get('payment_method', '').strip()
    if payment_method:
        orders_queryset = orders_queryset.filter(payments__method=payment_method).distinct()

    # Apply status filter
    if status_filter and status_filter != 'all':
        orders_queryset = orders_queryset.filter(status=status_filter)
    
    # Apply date filters
    today = timezone.now().date()
    if date_filter == 'today':
        orders_queryset = orders_queryset.filter(order_date__date=today)
    elif date_filter == 'week':
        week_start = today - timedelta(days=today.weekday())
        orders_queryset = orders_queryset.filter(order_date__date__gte=week_start)
    elif date_filter == 'month':
        month_start = today.replace(day=1)
        orders_queryset = orders_queryset.filter(order_date__date__gte=month_start)
    elif date_filter == 'custom' and start_date and end_date:
        try:
            start_date_obj = datetime.strptime(start_date, '%Y-%m-%d').date()
            end_date_obj = datetime.strptime(end_date, '%Y-%m-%d').date()
            orders_queryset = orders_queryset.filter(
                order_date__date__gte=start_date_obj,
                order_date__date__lte=end_date_obj
            )
        except ValueError:
            start_date = end_date = ''  # Clear invalid dates
    
    # Apply employee filter
    if employee_filter != 'all' and employee_filter:
        orders_queryset = orders_queryset.filter(owner_id=employee_filter)
    if not employee_filter:
        orders_queryset = orders_queryset.filter(owner=owner)

    # Apply amount range filters
    if min_amount:
        try:
            min_amount_value = Decimal(min_amount)
            orders_queryset = orders_queryset.filter(total_amount__gte=min_amount_value)
        except (ValueError, TypeError):
            min_amount = ''
    
    if max_amount:
        try:
            max_amount_value = Decimal(max_amount)
            orders_queryset = orders_queryset.filter(total_amount__lte=max_amount_value)
        except (ValueError, TypeError):
            max_amount = ''
    
    # Apply sorting
    valid_sort_options = [
        'order_date', '-order_date', 'total_amount', '-total_amount',
        'client__name', '-client__name', 'status', '-status'
    ]
    if sort_by in valid_sort_options:
        orders_queryset = orders_queryset.order_by(sort_by)
    else:
        orders_queryset = orders_queryset.order_by('-order_date')
    
    # Calculate summary statistics
    order_stats = orders_queryset.aggregate(
        total_orders=Count('id'),
        total_amount_sum=Sum('total_amount'),
        avg_amount=Avg('total_amount'),
        min_amount_stat=Min('total_amount'),
        max_amount_stat=Max('total_amount')
    )
    
    # Status distribution
    status_distribution = orders_queryset.values('status').annotate(
        count=Count('id')
    ).order_by('status')
    
    # Get all employees for filter dropdown
    employees = User.objects.filter(
        id__in=Order.objects.values_list('owner_id', flat=True).distinct()
    ).order_by('first_name', 'last_name')
    
    # Pagination
    paginator = Paginator(orders_queryset, 20)  # Show 20 orders per page
    page = request.GET.get('page')
    
    try:
        orders = paginator.page(page)
    except PageNotAnInteger:
        orders = paginator.page(1)
    except EmptyPage:
        orders = paginator.page(paginator.num_pages)
    
    # Check if filters are applied
    has_filters = bool(
        search_query or (status_filter and status_filter != 'all') or
        date_filter or employee_filter or min_amount or max_amount or payment_method
    )

    context = {
        'orders': orders,
        'search_query': search_query,
        'status_filter': status_filter,
        'payment_methods': PAYMENT_METHOD_CHOICES,
        'date_filter': date_filter,
        'start_date': start_date,
        'end_date': end_date,
        'employee_filter': employee_filter,
        'min_amount': min_amount,
        'max_amount': max_amount,
        'sort_by': sort_by,
        'total_orders': paginator.count,
        'has_search': bool(search_query),
        'has_filters': has_filters,
        'order_stats': order_stats,
        'status_distribution': status_distribution,
        'order_status_choices': ORDER_STATUS_CHOICES,
        'employees': employees,
        'today_date': today.strftime('%Y-%m-%d'),
    }
    
    return render(request, 'report/orders_report.html', context)


@login_required
def clients_full_report(request):
    """Generate a full report for all clients.
    This report will list all clients orders, we are going to implement filters by:
    - Today's orders
    - This week's orders
    - This month's orders
    - Custom range of dates
    - Search by employee
    - By payment status 
    - By order status
    - By payment method
    - Order type (delivery, pickup)
    """
    orders = Order.objects.select_related('client', 'owner').prefetch_related('items', 'payments')
    return render(request, 'report/clients_full_report.html', {'orders': orders})