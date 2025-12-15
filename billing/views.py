from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.contrib.auth.decorators import login_required

# Create your views here.

@login_required
def billable_orders(request, client_pk):
    from orders.services import get_client_order_without_bill
    from clients.models import Client

    client = get_object_or_404(Client, pk=client_pk)
    orders = get_client_order_without_bill(client)

    orders_data = [
        {
            'id': order.id,
            'order_date': order.order_date,
            'total_amount': order.total_amount,
            # Add other relevant fields as needed
        }
        for order in orders
    ]

    return JsonResponse({'orders': orders_data}, safe=False)