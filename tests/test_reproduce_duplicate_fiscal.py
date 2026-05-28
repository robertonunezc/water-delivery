import os
import django
import sys

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'water_delivery.settings')
django.setup()

from clients.models import Client, Address
from django.test import Client as HttpClient
from django.contrib.auth.models import User

# Create a superuser to login
user, created = User.objects.get_or_create(username='admin', is_staff=True, is_superuser=True)
if created:
    user.set_password('admin')
    user.save()

client_obj, _ = Client.objects.get_or_create(name='Test Client Dupe', type='corporate')
Address.objects.filter(client=client_obj).delete()

c = HttpClient()
c.login(username='admin', password='admin')

# Scenario 1: Create a Fiscal address and check the box
print("Scenario 1: Submitting new Fiscal address and checking the box")
url = f'/clients/{client_obj.id}/edit/?tab=addresses'
response = c.post(url, {
    'section': 'addresses',
    'addresses-TOTAL_FORMS': '1',
    'addresses-INITIAL_FORMS': '0',
    'addresses-MIN_NUM_FORMS': '0',
    'addresses-MAX_NUM_FORMS': '1000',
    'addresses-0-type': 'billing',
    'addresses-0-street': 'Fiscal Street',
    'addresses-0-locality': 'Locality',
    'addresses-0-municipality': 'Muni',
    'addresses-0-state': 'State',
    'addresses-0-zip_code': '12345',
    'addresses-0-country': 'Mexico',
    'addresses-0-active': 'on',
    'copy_address_for_all_inlines': 'on',
})

print(f"Number of addresses: {Address.objects.filter(client=client_obj).count()}")
for a in Address.objects.filter(client=client_obj):
    print(f" - {a.type}: {a.street}")

# Reset
Address.objects.filter(client=client_obj).delete()

# Scenario 2: Create a delivery address and check the box
print("\nScenario 2: Submitting new Delivery address and checking the box")
response = c.post(url, {
    'section': 'addresses',
    'addresses-TOTAL_FORMS': '1',
    'addresses-INITIAL_FORMS': '0',
    'addresses-MIN_NUM_FORMS': '0',
    'addresses-MAX_NUM_FORMS': '1000',
    'addresses-0-type': 'delivery',
    'addresses-0-street': 'Delivery Street',
    'addresses-0-locality': 'Locality',
    'addresses-0-municipality': 'Muni',
    'addresses-0-state': 'State',
    'addresses-0-zip_code': '12345',
    'addresses-0-country': 'Mexico',
    'addresses-0-active': 'on',
    'copy_address_for_all_inlines': 'on',
})

print(f"Number of addresses: {Address.objects.filter(client=client_obj).count()}")
for a in Address.objects.filter(client=client_obj):
    print(f" - {a.type}: {a.street}")
    
# Scenario 3: Modify delivery address and check the box when Fiscal already exists
print("\nScenario 3: Modify delivery address and check the box when Fiscal already exists")
del_addr = Address.objects.get(client=client_obj, type='delivery')
fisc_addr = Address.objects.get(client=client_obj, type='billing')

response = c.post(url, {
    'section': 'addresses',
    'addresses-TOTAL_FORMS': '2',
    'addresses-INITIAL_FORMS': '2',
    'addresses-MIN_NUM_FORMS': '0',
    'addresses-MAX_NUM_FORMS': '1000',
    'addresses-0-id': del_addr.id,
    'addresses-0-type': 'delivery',
    'addresses-0-street': 'Delivery Street Modified',
    'addresses-0-locality': 'Locality',
    'addresses-0-municipality': 'Muni',
    'addresses-0-state': 'State',
    'addresses-0-zip_code': '12345',
    'addresses-0-country': 'Mexico',
    'addresses-0-active': 'on',
    'addresses-1-id': fisc_addr.id,
    'addresses-1-type': 'billing',
    'addresses-1-street': 'Fiscal Street',
    'addresses-1-locality': 'Locality',
    'addresses-1-municipality': 'Muni',
    'addresses-1-state': 'State',
    'addresses-1-zip_code': '12345',
    'addresses-1-country': 'Mexico',
    'addresses-1-active': 'on',
    'copy_address_for_all_inlines': 'on',
})

print(f"Number of addresses: {Address.objects.filter(client=client_obj).count()}")
for a in Address.objects.filter(client=client_obj):
    print(f" - {a.type}: {a.street}")

