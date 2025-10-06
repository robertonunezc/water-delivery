from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.db.models import Q, Max, Min, Sum, Avg, Subquery, OuterRef
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from decimal import Decimal
from clients.models import Client, CreditTransaction


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
