from django.shortcuts import render
from .models import Client
# Create your views here.
def list(request):
    clients = Client.objects.all()
    return render(request, 'list_clients.html', {'clients': clients})