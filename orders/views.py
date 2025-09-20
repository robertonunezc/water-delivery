from django.shortcuts import render

# Create your views here.
def new_order(client_pk, request):
    
    return render(request, 'new_order.html', {})