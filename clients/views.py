from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Count, Q
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.contrib import messages
from datetime import date, datetime, timedelta
from calendar import monthrange
from .models import Client
from .forms import ManualCreditTransactionForm
from .services import get_upcoming_route_orders, get_recent_completed_route_orders
from orders.services import get_client_order_without_bill

@login_required
def list(request):
    # Get search query from request
    search_query = request.GET.get('search', '').strip()
    
    # Start with all clients
    clients_queryset = Client.objects.select_related().prefetch_related(
        'contacts', 'addresses'
    ).order_by('-created_at', 'name')
    
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
            Q(billing_data__rfc__icontains=search_query) |
            Q(billing_data__razon_social__icontains=search_query)
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
    
    context = {
        'clients': clients,
        'search_query': search_query,
        'total_clients': paginator.count,
        'has_search': bool(search_query),
    }
    
    return render(request, 'list_clients.html', context)

@login_required
def detail(request, pk):
    client = get_object_or_404(Client, pk=pk)
    first_day_of_month = date.today().replace(day=1)
    # Get client's orders with related data
    orders = client.orders.all().prefetch_related('items__product', 'payments').order_by('-created_at')
    
    # Get client's payments with related data
    payments = client.payments.filter(date__gte=first_day_of_month).select_related('order').order_by('-date')
    
    # Get credit and balance transactions
    balance_transactions = client.balance_transactions.all().select_related('reference_order', 'reference_payment', 'created_by').order_by('-created_at')
    credit_transactions = client.credit_transactions.all().select_related('reference_order', 'reference_payment', 'created_by').order_by('-created_at')
    
    # Combine all payment-related data for the recent transactions view
    all_payment_data = []
    
    # Add regular payments
    for payment in payments:
        all_payment_data.append({
            'type': 'payment',
            'id': payment.id,
            'date': payment.date,
            'amount': payment.amount,
            'method': payment.get_method_display(),
            'status': payment.get_status_display(),
            'status_class': 'success' if payment.status == 'completed' else 'warning' if payment.status == 'pending' else 'danger',
            'order_id': payment.order.id if payment.order else None,
            'description': f'Pago de orden #{payment.order.id}' if payment.order else 'Pago general',
            'is_positive': True,  # Regular payments are always positive from client perspective
            'object': payment
        })
    
    # Add balance transactions  
    for balance_tx in balance_transactions:
        # Skip balance transactions that are already represented as payments
        if balance_tx.reference_payment:
            continue
            
        status_class = 'success' if balance_tx.transaction_type in ['deposit', 'refund', 'transfer_in'] else 'info'
        is_positive = balance_tx.transaction_type in ['deposit', 'refund', 'transfer_in', 'adjustment']
        all_payment_data.append({
            'type': 'balance_transaction',
            'id': balance_tx.id,
            'date': balance_tx.created_at,
            'amount': balance_tx.amount,
            'method': balance_tx.get_transaction_type_display(),
            'status': 'Completado',
            'status_class': status_class,
            'order_id': balance_tx.reference_order.id if balance_tx.reference_order else None,
            'description': balance_tx.notes or balance_tx.get_transaction_type_display(),
            'is_positive': is_positive,
            'object': balance_tx
        })
    
    # Add credit transactions
    for credit_tx in credit_transactions:
        # Skip credit transactions that are already represented as payments
        if credit_tx.reference_payment:
            continue
            
        status_class = 'warning' if credit_tx.transaction_type in ['purchase', 'interest', 'fee'] else 'success'
        is_positive = credit_tx.transaction_type in ['payment', 'adjustment', 'forgiveness', 'correction']
        all_payment_data.append({
            'type': 'credit_transaction',
            'id': credit_tx.id,
            'date': credit_tx.created_at,
            'amount': credit_tx.amount,
            'method': credit_tx.get_transaction_type_display(),
            'status': 'Completado',
            'status_class': status_class,
            'order_id': credit_tx.reference_order.id if credit_tx.reference_order else None,
            'description': credit_tx.notes or credit_tx.get_transaction_type_display(),
            'is_positive': is_positive,
            'object': credit_tx
        })
    
    # Sort all payment data by date (most recent first)
    all_payment_data.sort(key=lambda x: x['date'], reverse=True)
    
    # Calculate client statistics
    total_orders = orders.count()
    total_spent = payments.filter(status='completed').aggregate(total=Sum('amount'))['total'] or 0
    pending_orders = orders.filter(status='pending').count()
    completed_orders = orders.filter(status='completed').count()
    
    # Get client's contacts and addresses
    contacts = client.contacts.all()
    addresses = client.addresses.filter(active=True)
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
    context = {
        'client': client,
        'date_since': first_day_of_month,
        'orders': orders[:10],  # Limit to recent 10 orders for performance
        'payments': payments[:10],  # Limit to recent 10 payments for backward compatibility
        'all_payment_data': all_payment_data[:10],  # Combined payment data - limit to recent 10
        'contacts': contacts,
        'addresses': addresses,
        'billing_data': billing_data,
        'billing_frequency': billing_frequency,
        'route_clients': route_clients,
        'upcoming_route_orders': upcoming_route_orders,
        'recent_completed_routes': recent_completed_routes,
        'debt_percentage': int(client.current_debt / client.credit_limit * 100) if client.credit_limit > 0 else 0, 
        'stats': {
            'total_orders': total_orders,
            'total_spent': total_spent,
            'pending_orders': pending_orders,
            'completed_orders': completed_orders,
        }
    }
    
    return render(request, 'client_detail.html', context)

@login_required
def client_orders(request, client_pk):
    client = get_object_or_404(Client, pk=client_pk)
    orders = get_client_order_without_bill(client)
    return JsonResponse({'orders': orders}, safe=False)

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
            requires_note_for_credit=body.get('requires_note_for_credit'),
            address_link=body.get('address_link'),
            requires_billing=body.get('requires_billing'),
            billing_override_enabled=body.get('billing_override_enabled'),
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
                'requires_note_for_credit': updated_client.requires_note_for_credit,
                'billing_override_enabled': updated_client.billing_override_enabled,
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