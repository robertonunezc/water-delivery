# Django Admin Dynamic Order Filtering for BillingOrder

This document describes the JavaScript-based dynamic filtering implementation for the `BillingOrder` Django Admin form.

## Overview

When creating or editing a `BillingOrder` in Django Admin, the `order` field is dynamically populated based on the selected `billing_record`. This ensures users only see orders that:
- Belong to the same client as the selected billing record
- Have not already been billed (not associated with any `BillingRecord`)
- Have `order_date >= billing_record.date`

## Architecture

### Backend Components

#### 1. Admin URLs (`billing/admin.py`)

Two custom admin URLs are registered in `BillingOrderAdmin.get_urls()`:

```python
# Get billable orders for a client
/admin/billing/billingorder/billable-orders/<client_pk>/?billing_record_id=<id>

# Get client info from a billing record
/admin/billing/billingorder/billing-record/<billing_record_pk>/client/
```

#### 2. Admin Views

**`billable_orders_json(request, client_pk)`**
- Returns JSON list of unbilled orders for the given client
- Accepts optional `billing_record_id` query parameter for date filtering
- Filters: `client=client_pk`, `billing_orders__isnull=True`, `order_date >= billing_record.date`
- Response format:
```json
{
  "orders": [
    {
      "id": 123,
      "order_date": "2025-12-15T10:30:00",
      "total_amount": "150.00",
      "display": "Order #123 - 2025-12-15 - $150.00"
    }
  ]
}
```

**`get_billing_record_client(request, billing_record_pk)`**
- Returns client info for a given billing record
- Response format:
```json
{
  "client_id": 45,
  "client_name": "Client A"
}
```

#### 3. ModelForm Media (`BillingOrderAdminForm`)

The form includes a `Media` class to load the JavaScript:

```python
class BillingOrderAdminForm(forms.ModelForm):
    class Media:
        js = ('admin/js/billing_order_admin.js',)
```

The `billing_record` field has a custom data attribute:
- `data-enable-dynamic-orders="true"` - enables JavaScript behavior

### Frontend Component

#### JavaScript File
**Location:** `billing/static/admin/js/billing_order_admin.js`

**Behavior:**
1. On page load, finds `#id_billing_record` and `#id_order` fields
2. Checks for `data-enable-dynamic-orders` attribute before activating
3. Listens for changes on the `billing_record` select field
4. When changed:
   - Fetches client_id from the selected billing record
   - Fetches billable orders for that client (with billing_record_id for date filtering)
   - Clears and repopulates the `order` select field
   - Auto-selects if only one order is available

**Key Functions:**
- `fetchClientId(billingRecordId)` - Gets client info via admin URL
- `fetchBillableOrders(clientId, billingRecordId)` - Gets filtered orders
- `clearOrderSelect(selectElement)` - Clears order dropdown
- `populateOrderSelect(selectElement, orders)` - Populates with new options

## Usage

### Admin Interface

1. Navigate to `/admin/billing/billingorder/add/` or edit an existing `BillingOrder`
2. Select a `BillingRecord` from the dropdown
3. The `Order` dropdown automatically populates with eligible orders
4. Select an order and save

### For Developers

**Adding to Other Admin Forms:**

1. Add the Media class to your ModelForm:
```python
class MyForm(forms.ModelForm):
    class Media:
        js = ('admin/js/my_custom_script.js',)
```

2. Add data attributes to enable JavaScript:
```python
self.fields['my_field'].widget.attrs['data-enable-feature'] = 'true'
```

3. Register custom admin URLs:
```python
class MyAdmin(admin.ModelAdmin):
    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('my-endpoint/', self.admin_site.admin_view(self.my_view)),
        ]
        return custom_urls + urls
```

## Testing

### Unit Tests
Tests are located in `billing/tests.py`:
- `test_order_queryset_filters_by_client_date_and_unbilled` - Server-side filtering
- `test_order_queryset_includes_current_order_on_edit` - Edit mode behavior
- `test_validation_fails_when_sum_exceeds_billing_amount` - Amount validation
- `test_validation_passes_at_boundary_equal_to_billing_amount` - Boundary validation

Run tests:
```bash
python manage.py test billing
```

### Manual Testing

1. Create test data:
   - Create a client
   - Create a billing record for that client
   - Create multiple orders for the same client (some before, some after billing_record.date)
   - Link one order to another billing record

2. Test the admin form:
   - Navigate to BillingOrder add form
   - Select the billing record
   - Verify only eligible orders appear in the dropdown
   - Verify the JavaScript console shows no errors

### Verification Script

Run the verification script to check all components:
```bash
python verify_admin_changes.py
```

## Security

- All admin views use `self.admin_site.admin_view()` decorator
- Ensures only staff members can access the endpoints
- CSRF protection via Django's built-in middleware
- Uses `credentials: 'same-origin'` in fetch requests

## Browser Compatibility

The JavaScript uses modern ES6+ features:
- Arrow functions
- Template literals
- Fetch API
- Promises

**Supported Browsers:**
- Chrome 45+
- Firefox 40+
- Safari 10+
- Edge 14+

For older browsers, consider adding polyfills.

## Troubleshooting

### Orders Not Loading

**Issue:** Order dropdown stays empty after selecting billing record

**Checks:**
1. Open browser DevTools → Network tab
2. Select a billing record
3. Check for XHR requests to `/admin/billing/billingorder/`
4. Verify responses are 200 OK
5. Check Console for JavaScript errors

**Common causes:**
- JavaScript file not loaded (check Media class)
- CSRF token issues (ensure same-origin credentials)
- Incorrect URL patterns (check `get_urls()` method)

### Wrong Orders Appearing

**Issue:** Orders from wrong client or already billed orders appear

**Checks:**
1. Verify `billing_record.client` matches expected client
2. Check database: `SELECT * FROM billing_billingorder WHERE order_id = <id>`
3. Verify `order_date` vs `billing_record.date`

**Solution:** Review filtering logic in `billable_orders_json` view

### Static Files Not Loading

**Issue:** JavaScript file returns 404

**Checks:**
1. Verify file exists at `billing/static/admin/js/billing_order_admin.js`
2. Run `python manage.py collectstatic` in production
3. Check `STATIC_URL` and `STATIC_ROOT` settings
4. Verify `django.contrib.staticfiles` in `INSTALLED_APPS`

## Future Enhancements

Potential improvements:
- Add loading spinner while fetching orders
- Show "No orders available" message when empty
- Add search/filter within the order dropdown
- Preserve order selection when validation fails
- Add keyboard navigation support
- Display order details on hover (tooltip)

## References

- Django Admin Documentation: https://docs.djangoproject.com/en/5.2/ref/contrib/admin/
- Django Static Files: https://docs.djangoproject.com/en/5.2/howto/static-files/
- Fetch API: https://developer.mozilla.org/en-US/docs/Web/API/Fetch_API
