#!/usr/bin/env python
"""
Test script for credit payment control functionality
"""
import os
import sys
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'water_delivery.settings')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
django.setup()

from clients.models import Client
from decimal import Decimal

def test_credit_payment_controls():
    """Test the new credit payment control fields and methods"""
    
    print("=" * 60)
    print("TESTING CREDIT PAYMENT CONTROLS")
    print("=" * 60)
    
    # Test 1: Default values
    print("\n1. Testing default values...")
    client1 = Client.objects.create(
        name="Test Client 1",
        credit_limit=Decimal('1000.00')
    )
    print(f"   can_pay_with_credit: {client1.can_pay_with_credit} (should be True)")
    assert client1.can_pay_with_credit == True
    print("   ✓ Default values correct")
    
    # Test 2: can_use_credit_for_payment method
    print("\n2. Testing can_use_credit_for_payment method...")
    
    # Client with credit disabled and no credit balance
    client3 = Client.objects.create(
        name="Test Client 3",
        can_pay_with_credit=False,
        credit_limit=Decimal('1000.00'),
        current_debt=Decimal('1000.00')  # No available credit
    )
    print(f"   Client 3 - can_pay_with_credit=False, available_credit=0: {client3.can_use_credit_for_payment()} (should be False)")
    assert client3.can_use_credit_for_payment() == False
    
    # Client with credit disabled but has available credit
    client4 = Client.objects.create(
        name="Test Client 4",
        can_pay_with_credit=False,
        credit_limit=Decimal('1000.00'),
        current_debt=Decimal('500.00')  # Has available credit
    )
    print(f"   Client 4 - can_pay_with_credit=False, available_credit=500: {client4.can_use_credit_for_payment()} (should be False)")
    assert client4.can_use_credit_for_payment() == False
    
    # Client with credit enabled
    client5 = Client.objects.create(
        name="Test Client 5",
        can_pay_with_credit=True,
        credit_limit=Decimal('1000.00'),
        current_debt=Decimal('1000.00')  # No available credit
    )
    print(f"   Client 5 - can_pay_with_credit=True, available_credit=0: {client5.can_use_credit_for_payment()} (should be False)")
    assert client5.can_use_credit_for_payment() == False
    
    # Test 3: validate_credit_payment method
    print("\n3. Testing validate_credit_payment method...")
    
    # Test with client that can't pay with credit
    result = client3.validate_credit_payment(Decimal('100.00'))
    print(f"   Client 3 validation result: {result}")
    assert result['success'] == False
    assert result['error_code'] == 'CREDIT_DISABLED'
    
    # Test with insufficient credit
    client4.can_pay_with_credit = True
    result = client4.validate_credit_payment(Decimal('600.00'))  # Available: 500
    print(f"   Client 4 insufficient credit: {result}")
    assert result['success'] == False
    assert result['error_code'] == 'CREDIT_LIMIT_EXCEEDED'
    
    # Notes are now optional for credit payments
    client6 = Client.objects.create(
        name="Test Client 6",
        can_pay_with_credit=True,
        credit_limit=Decimal('1000.00'),
        current_debt=Decimal('0.00')
    )
    result = client6.validate_credit_payment(Decimal('100.00'))
    print(f"   Client 6 without note: {result}")
    assert result['success'] == True
    
    # Test 4: can_afford_order method
    print("\n4. Testing can_afford_order method...")
    
    # Client that can't use credit
    client3.balance = Decimal('200.00')
    client3.save()
    
    print(f"   Client 3 can afford $150 order: {client3.can_afford_order(Decimal('150.00'))} (should be True - has balance)")
    assert client3.can_afford_order(Decimal('150.00')) == True
    
    print(f"   Client 3 can afford $300 order: {client3.can_afford_order(Decimal('300.00'))} (should be False - not enough balance, can't use credit)")
    assert client3.can_afford_order(Decimal('300.00')) == False
    
    # Client that can use credit
    client5.balance = Decimal('200.00')
    client5.current_debt = Decimal('500.00')  # Available credit: 500
    client5.save()
    
    print(f"   Client 5 can afford $600 order: {client5.can_afford_order(Decimal('600.00'))} (should be True - balance + credit)")
    assert client5.can_afford_order(Decimal('600.00')) == True
    
    print(f"   Client 5 can afford $800 order: {client5.can_afford_order(Decimal('800.00'))} (should be False - exceeds balance + credit)")
    assert client5.can_afford_order(Decimal('800.00')) == False
    
    print("\n" + "=" * 60)
    print("ALL TESTS PASSED! ✓")
    print("=" * 60)
    
    # Clean up
    Client.objects.filter(name__startswith="Test Client").delete()

if __name__ == "__main__":
    test_credit_payment_controls()
