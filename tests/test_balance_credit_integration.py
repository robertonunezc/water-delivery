#!/usr/bin/env python
"""
Test script to demonstrate the balance and credit payment integration.
This script shows how the Payment model automatically handles balance and credit payments.
"""

import os
import sys
import django
from decimal import Decimal

# Setup Django environment
sys.path.append('/Users/robertonunez/Documents/Dev/water-delivery')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'water_delivery.settings')
django.setup()

from clients.models import Client
from payment.models import Payment
from orders.models import Order  # Assuming this exists


def test_balance_payment():
    """Test payment using client balance"""
    print("\n=== Testing Balance Payment ===")
    
    # Create or get a test client
    client, created = Client.objects.get_or_create(
        name="Test Client Balance",
        defaults={
            'balance': Decimal('100.00'),
            'credit_limit': Decimal('50.00'),
            'current_debt': Decimal('0.00')
        }
    )
    
    print(f"Client: {client.name}")
    print(f"Initial Balance: ${client.balance}")
    print(f"Initial Debt: ${client.current_debt}")
    
    # Try to create a balance payment
    try:
        # Create a mock order (you might need to adjust this based on your Order model)
        order = Order.objects.create(
            client=client,
            total_amount=Decimal('30.00'),
            status='pending'
        ) if hasattr(Order, 'objects') else type('MockOrder', (), {'id': 1, 'total_amount': Decimal('30.00')})()
        
        # Create payment using balance
        payment = Payment(
            amount=Decimal('30.00'),
            method='balance',
            client=client,
            order=order,
            status='completed'
        )
        
        # Validate payment
        payment.clean()
        print("✓ Payment validation passed")
        
        # Save payment (this will automatically deduct from balance)
        payment.save()
        print("✓ Payment saved successfully")
        
        # Refresh client from database
        client.refresh_from_db()
        print(f"New Balance: ${client.balance}")
        print(f"Balance Used: ${payment.balance_used}")
        
        return payment
        
    except Exception as e:
        print(f"✗ Error: {e}")
        return None


def test_credit_payment():
    """Test payment using client credit"""
    print("\n=== Testing Credit Payment ===")
    
    # Create or get a test client
    client, created = Client.objects.get_or_create(
        name="Test Client Credit",
        defaults={
            'balance': Decimal('0.00'),
            'credit_limit': Decimal('100.00'),
            'current_debt': Decimal('20.00')
        }
    )
    
    print(f"Client: {client.name}")
    print(f"Initial Balance: ${client.balance}")
    print(f"Initial Debt: ${client.current_debt}")
    print(f"Available Credit: ${client.get_available_credit()}")
    
    # Try to create a credit payment
    try:
        # Create a mock order
        order = Order.objects.create(
            client=client,
            total_amount=Decimal('40.00'),
            status='pending'
        ) if hasattr(Order, 'objects') else type('MockOrder', (), {'id': 2, 'total_amount': Decimal('40.00')})()
        
        # Create payment using credit
        payment = Payment(
            amount=Decimal('40.00'),
            method='credit',
            client=client,
            order=order,
            status='completed'
        )
        
        # Validate payment
        payment.clean()
        print("✓ Payment validation passed")
        
        # Save payment (this will automatically add to debt)
        payment.save()
        print("✓ Payment saved successfully")
        
        # Refresh client from database
        client.refresh_from_db()
        print(f"New Debt: ${client.current_debt}")
        print(f"Credit Used: ${payment.credit_used}")
        print(f"Remaining Available Credit: ${client.get_available_credit()}")
        
        return payment
        
    except Exception as e:
        print(f"✗ Error: {e}")
        return None


def test_mixed_payment():
    """Test automatic payment using both balance and credit"""
    print("\n=== Testing Mixed Payment (Balance + Credit) ===")
    
    # Create or get a test client
    client, created = Client.objects.get_or_create(
        name="Test Client Mixed",
        defaults={
            'balance': Decimal('25.00'),
            'credit_limit': Decimal('100.00'),
            'current_debt': Decimal('10.00')
        }
    )
    
    print(f"Client: {client.name}")
    print(f"Initial Balance: ${client.balance}")
    print(f"Initial Debt: ${client.current_debt}")
    print(f"Available Credit: ${client.get_available_credit()}")
    
    # Try to create a mixed payment using client method
    try:
        # Create a mock order
        order = Order.objects.create(
            client=client,
            total_amount=Decimal('80.00'),
            status='pending'
        ) if hasattr(Order, 'objects') else type('MockOrder', (), {'id': 3, 'total_amount': Decimal('80.00')})()
        
        # Use client method to create payments automatically
        result = client.create_payment_for_order(order)
        
        if result['success']:
            print("✓ Mixed payment created successfully")
            print(f"Payments created: {len(result['payments'])}")
            
            for payment in result['payments']:
                print(f"  - {payment.get_method_display()}: ${payment.amount}")
            
            # Refresh client from database
            client.refresh_from_db()
            print(f"Final Balance: ${client.balance}")
            print(f"Final Debt: ${client.current_debt}")
            print(f"Final Available Credit: ${client.get_available_credit()}")
            
            return result['payments']
        else:
            print(f"✗ Payment failed: {result['error']}")
            return None
        
    except Exception as e:
        print(f"✗ Error: {e}")
        return None


def test_insufficient_funds():
    """Test payment validation when client doesn't have enough funds"""
    print("\n=== Testing Insufficient Funds Validation ===")
    
    # Create client with limited funds
    client, created = Client.objects.get_or_create(
        name="Test Client Poor",
        defaults={
            'balance': Decimal('10.00'),
            'credit_limit': Decimal('20.00'),
            'current_debt': Decimal('15.00')
        }
    )
    
    print(f"Client: {client.name}")
    print(f"Balance: ${client.balance}")
    print(f"Available Credit: ${client.get_available_credit()}")
    print(f"Total Available: ${client.balance + client.get_available_credit()}")
    
    # Try to create a payment that exceeds available funds
    try:
        order = Order.objects.create(
            client=client,
            total_amount=Decimal('50.00'),
            status='pending'
        ) if hasattr(Order, 'objects') else type('MockOrder', (), {'id': 4, 'total_amount': Decimal('50.00')})()
        
        payment = Payment(
            amount=Decimal('50.00'),
            method='balance',
            client=client,
            order=order,
            status='completed'
        )
        
        # This should raise a validation error
        payment.clean()
        print("✗ Validation should have failed!")
        
    except Exception as e:
        print(f"✓ Validation correctly failed: {e}")


if __name__ == "__main__":
    print("Starting Balance and Credit Payment Integration Tests")
    print("=" * 60)
    
    # Run tests
    test_balance_payment()
    test_credit_payment()
    test_mixed_payment()
    test_insufficient_funds()
    
    print("\n" + "=" * 60)
    print("Tests completed!")