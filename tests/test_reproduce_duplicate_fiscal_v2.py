import os
import django
import sys

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'water_delivery.settings')
django.setup()

from clients.models import Client, Address
from django.test import Client as HttpClient
from django.contrib.auth.models import User
from clients.views import _submission_has_billing_address, _copy_delivery_to_billing_if_missing

user, created = User.objects.get_or_create(username='admin', is_staff=True, is_superuser=True)
if created:
    user.set_password('admin')
    user.save()

client_obj, _ = Client.objects.get_or_create(name='Test Client Dupe', type='corporate')
Address.objects.filter(client=client_obj).delete()

c = HttpClient()
c.login(username='admin', password='admin')

url = f'/clients/{client_obj.id}/editar/?tab=addresses'

print("--- SCENARIO: Submitting ONLY Delivery address with checkbox ---")
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
print(f"Status Code: {response.status_code}")

print(f"Number of addresses: {Address.objects.filter(client=client_obj).count()}")
for a in Address.objects.filter(client=client_obj):
    print(f" - ID: {a.id}, TYPE: {a.type}, STREET: {a.street}")
    
Address.objects.filter(client=client_obj).delete()

print("\n--- SCENARIO: Submitting ONLY Fiscal address with checkbox ---")
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
print(f"Status Code: {response.status_code}")
if response.status_code == 200:
    print(response.content.decode('utf-8'))

print(f"Number of addresses: {Address.objects.filter(client=client_obj).count()}")
for a in Address.objects.filter(client=client_obj):
    print(f" - ID: {a.id}, TYPE: {a.type}, STREET: {a.street}")

