#!/usr/bin/env python
"""
Quick verification script for Django admin changes
"""
import os
import sys
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'water_delivery.settings')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
django.setup()

print("✓ Django setup successful")

# Import the admin module
try:
    from billing.admin import BillingOrderAdmin
    print("✓ BillingOrderAdmin imported successfully")
except Exception as e:
    print(f"✗ Error importing BillingOrderAdmin: {e}")
    sys.exit(1)

# Check if custom URLs method exists
if hasattr(BillingOrderAdmin, 'get_urls'):
    print("✓ get_urls method exists")
else:
    print("✗ get_urls method not found")
    sys.exit(1)

# Check if custom views exist
if hasattr(BillingOrderAdmin, 'billable_orders_json'):
    print("✓ billable_orders_json view exists")
else:
    print("✗ billable_orders_json view not found")
    sys.exit(1)

if hasattr(BillingOrderAdmin, 'get_billing_record_client'):
    print("✓ get_billing_record_client view exists")
else:
    print("✗ get_billing_record_client view not found")
    sys.exit(1)

# Check JavaScript file exists
import os.path
js_path = 'billing/static/admin/js/billing_order_admin.js'
if os.path.exists(js_path):
    print(f"✓ JavaScript file exists at {js_path}")
else:
    print(f"✗ JavaScript file not found at {js_path}")
    sys.exit(1)

# Check Media class
from billing.admin import BillingOrderAdminForm
if hasattr(BillingOrderAdminForm, 'Media'):
    print("✓ Media class exists in BillingOrderAdminForm")
    if hasattr(BillingOrderAdminForm.Media, 'js'):
        print(f"✓ JS files configured: {BillingOrderAdminForm.Media.js}")
    else:
        print("✗ Media.js not configured")
        sys.exit(1)
else:
    print("✗ Media class not found in BillingOrderAdminForm")
    sys.exit(1)

print("\n✓ All checks passed! Admin changes are properly configured.")
