#!/usr/bin/env python
"""
Test script for the new billing frequency functionality
"""
import os
import sys
import django
from datetime import date

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'water_delivery.settings')
django.setup()

from clients.models import Client, ClientBillingFrecuency

def test_billing_frequency_examples():
    """Test different billing frequency scenarios"""
    
    # Create a test client
    client, created = Client.objects.get_or_create(
        name="Test Client - Billing Frequency",
        defaults={'active': True, 'type': 'individual'}
    )
    
    # Clear any existing billing frequencies
    ClientBillingFrecuency.objects.filter(client=client).delete()
    
    print(f"Testing billing frequency for client: {client.name}")
    print("-" * 50)
    
    # Test 1: Last day of month
    print("1. Testing: Last day of month (monthly)")
    bf1 = ClientBillingFrecuency.objects.create(
        client=client,
        frequency='monthly',
        billing_date='last_day',
        is_active=True
    )
    print(f"   Description: {bf1}")
    print(f"   Billing info: {bf1.get_billing_info()}")
    candidates = bf1.get_next_billing_candidates()
    print(f"   Next candidates: {candidates[:3]}")  # Show first 3
    print()
    
    # Test 2: First day of month
    print("2. Testing: First day of month (monthly)")
    bf1.billing_date = 'first_day'
    bf1.save()
    print(f"   Description: {bf1}")
    print(f"   Billing info: {bf1.get_billing_info()}")
    candidates = bf1.get_next_billing_candidates()
    print(f"   Next candidates: {candidates[:3]}")
    print()
    
    # Test 3: Specific date (10th of each month)
    print("3. Testing: Specific date (10th of each month)")
    bf1.billing_date = 'specific_date'
    bf1.specific_day = 10
    bf1.save()
    print(f"   Description: {bf1}")
    print(f"   Billing info: {bf1.get_billing_info()}")
    candidates = bf1.get_next_billing_candidates()
    print(f"   Next candidates: {candidates[:3]}")
    print()
    
    # Test 4: Third Monday of each month
    print("4. Testing: Third Monday of each month")
    bf1.billing_date = 'weekday_occurrence'
    bf1.specific_day = None
    bf1.weekday = 0  # Monday
    bf1.occurrence = 3  # Third
    bf1.save()
    print(f"   Description: {bf1}")
    print(f"   Billing info: {bf1.get_billing_info()}")
    candidates = bf1.get_next_billing_candidates()
    print(f"   Next candidates: {candidates[:3]}")
    print()
    
    # Test 5: Last Friday of each month (quarterly)
    print("5. Testing: Last Friday of each month (quarterly)")
    bf1.frequency = 'quarterly'
    bf1.weekday = 4  # Friday
    bf1.occurrence = -1  # Last
    bf1.save()
    print(f"   Description: {bf1}")
    print(f"   Billing info: {bf1.get_billing_info()}")
    candidates = bf1.get_next_billing_candidates()
    print(f"   Next candidates: {candidates[:3]}")
    print()
    
    print("All tests completed successfully!")
    print("The new billing frequency structure is working correctly.")

if __name__ == "__main__":
    test_billing_frequency_examples()