import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'water_delivery.settings')
django.setup()

from clients.models import Client
for client in Client.objects.all()[:5]:
    has_addr = client.billing_info.effective.has_address
    print(f"Client {client.id} - requires_billing: {client.requires_billing}, has_address: {has_addr}")
