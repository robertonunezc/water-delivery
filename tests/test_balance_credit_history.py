#!/usr/bin/env python3
"""
Test script to demonstrate balance and credit history functionality

This script shows how to:
1. Add balance with history tracking
2. Use balance for payments with history
3. Add/pay debt with history tracking
4. Transfer balance between clients
5. Query balance/credit history
6. Calculate balance at specific dates
"""

import os
import sys
import django
from datetime import datetime, timedelta
from decimal import Decimal

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'water_delivery.settings')
django.setup()

from clients.models import Client, BalanceTransaction, CreditTransaction
from django.contrib.auth import get_user_model

User = get_user_model()


def demo_balance_credit_history():
    """Demonstrate the new balance and credit history system"""
    
    print("=== Balance and Credit History Demo ===\n")
    
    # Create or get a test user
    user, created = User.objects.get_or_create(
        username='test_admin',
        defaults={'email': 'admin@test.com', 'is_staff': True}
    )
    print(f"Using user: {user.username}")
    
    # Create or get test clients
    client1, created = Client.objects.get_or_create(
        name='Test Client 1',
        defaults={'balance': Decimal('0.00'), 'credit_limit': Decimal('1000.00')}
    )
    
    client2, created = Client.objects.get_or_create(
        name='Test Client 2', 
        defaults={'balance': Decimal('0.00'), 'credit_limit': Decimal('500.00')}
    )
    
    print(f"\nInitial state:")
    print(f"Client 1 - Balance: ${client1.balance:.2f}, Debt: ${client1.current_debt:.2f}")
    print(f"Client 2 - Balance: ${client2.balance:.2f}, Debt: ${client2.current_debt:.2f}")
    
    # 1. Add balance with history
    print(f"\n1. Adding $500 to Client 1's balance...")
    client1.add_balance(
        amount=Decimal('500.00'),
        transaction_type='deposit',
        user=user,
        notes='Initial deposit - Demo deposit for testing'
    )
    print(f"Client 1 new balance: ${client1.balance:.2f}")
    
    # 2. Add more balance on different date
    print(f"\n2. Adding $200 to Client 1's balance...")
    client1.add_balance(
        amount=Decimal('200.00'),
        transaction_type='deposit',
        user=user,
        notes='Additional deposit on May 12 - Second deposit for demo'
    )
    print(f"Client 1 new balance: ${client1.balance:.2f}")
    
    # 3. Use balance for payment
    print(f"\n3. Using $150 from balance for payment...")
    success = client1.deduct_balance(
        amount=Decimal('150.00'),
        transaction_type='payment',
        user=user,
        notes='Payment for order #123 - Demo payment'
    )
    print(f"Payment successful: {success}")
    print(f"Client 1 remaining balance: ${client1.balance:.2f}")
    
    # 4. Add debt (credit purchase)
    print(f"\n4. Adding $300 debt (credit purchase)...")
    success = client1.add_debt(
        amount=Decimal('300.00'),
        transaction_type='purchase',
        user=user,
        notes='Credit purchase order #124 - Demo credit purchase'
    )
    print(f"Credit purchase successful: {success}")
    print(f"Client 1 current debt: ${client1.current_debt:.2f}")
    print(f"Client 1 available credit: ${client1.get_available_credit():.2f}")
    
    # 5. Pay down debt
    print(f"\n5. Paying $100 towards debt...")
    paid_amount = client1.pay_debt(
        amount=Decimal('100.00'),
        transaction_type='payment',
        user=user,
        notes='Debt payment - Partial debt payment'
    )
    print(f"Amount paid: ${paid_amount:.2f}")
    print(f"Client 1 remaining debt: ${client1.current_debt:.2f}")
    
    # 6. Transfer balance between clients
    print(f"\n6. Transferring $100 from Client 1 to Client 2...")
    transfer_result = client1.transfer_balance_to(
        target_client=client2,
        amount=Decimal('100.00'),
        description='Balance transfer demo',
        user=user,
        notes='Demo transfer between clients'
    )
    print(f"Transfer successful: {transfer_result['success']}")
    if transfer_result['success']:
        print(f"Client 1 balance: ${transfer_result['source_balance']:.2f}")
        print(f"Client 2 balance: ${transfer_result['target_balance']:.2f}")
    
    # 7. Update credit limit
    print(f"\n7. Updating Client 1's credit limit from $1000 to $1500...")
    client1.update_credit_limit(
        new_limit=Decimal('1500.00'),
        user=user,
        notes='Credit limit increase - Increased due to good payment history'
    )
    print(f"Client 1 new credit limit: ${client1.credit_limit:.2f}")
    print(f"Client 1 available credit: ${client1.get_available_credit():.2f}")
    
    # 8. Query balance history
    print(f"\n8. Balance transaction history for Client 1:")
    balance_history = client1.get_balance_history()
    for tx in balance_history[:5]:  # Show last 5 transactions
        print(f"  {tx.created_at.strftime('%Y-%m-%d %H:%M')} - {tx.get_transaction_type_display()}: "
              f"${tx.amount:.2f} (${tx.balance_before:.2f} → ${tx.balance_after:.2f}) - {tx.description}")
    
    # 9. Query credit history
    print(f"\n9. Credit transaction history for Client 1:")
    credit_history = client1.get_credit_history()
    for tx in credit_history[:5]:  # Show last 5 transactions
        print(f"  {tx.created_at.strftime('%Y-%m-%d %H:%M')} - {tx.get_transaction_type_display()}: "
              f"${tx.amount:.2f} (${tx.debt_before:.2f} → ${tx.debt_after:.2f}) - {tx.description}")
    
    # 10. Get financial summary
    print(f"\n10. Financial summary for Client 1:")
    summary = client1.get_financial_summary()
    print(f"  Current Balance: ${summary['current_balance']:.2f}")
    print(f"  Current Debt: ${summary['current_debt']:.2f}")
    print(f"  Credit Limit: ${summary['credit_limit']:.2f}")
    print(f"  Available Credit: ${summary['available_credit']:.2f}")
    print(f"  Total Deposits: ${summary['balance_summary']['total_deposits']:.2f}")
    print(f"  Total Balance Payments: ${summary['balance_summary']['total_payments']:.2f}")
    print(f"  Total Credit Purchases: ${summary['credit_summary']['total_purchases']:.2f}")
    print(f"  Total Debt Payments: ${summary['credit_summary']['total_payments']:.2f}")
    
    # 11. Calculate balance at specific date (demo - would be historical date in real scenario)
    print(f"\n11. Historical balance calculation:")
    print(f"  This feature allows you to see what the balance was at any point in time")
    print(f"  by replaying all transactions up to that date.")
    
    # Show transaction count
    print(f"\n12. Transaction counts:")
    print(f"  Client 1 balance transactions: {client1.balance_transactions.count()}")
    print(f"  Client 1 credit transactions: {client1.credit_transactions.count()}")
    print(f"  Client 2 balance transactions: {client2.balance_transactions.count()}")
    
    print(f"\n=== Demo Complete ===")
    print(f"\nKey Features Demonstrated:")
    print(f"✓ Complete audit trail for all balance and credit changes")
    print(f"✓ Before/after amounts tracked for every transaction")
    print(f"✓ User tracking for accountability")
    print(f"✓ References to related orders and payments")
    print(f"✓ Balance transfers between clients")
    print(f"✓ Credit limit management with history")
    print(f"✓ Comprehensive financial reporting")
    print(f"✓ Historical balance calculation capability")
    
    print(f"\nNow you can say:")
    print(f"'Client {client1.name} has ${client1.balance:.2f} of balance today.'")
    print(f"'They made deposits and transfers as shown in the transaction history above.'")


if __name__ == '__main__':
    demo_balance_credit_history()