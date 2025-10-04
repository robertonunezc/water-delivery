# Credit Payment Control Implementation

## Overview
This implementation adds fine-grained control over credit payments for clients, allowing administrators to restrict credit usage and require notes for audit purposes.

## New Fields Added to Client Model

### 1. `can_pay_with_credit` (Boolean, default: True)
- **Purpose**: Controls whether a client can use credit for payments
- **Behavior**: 
  - When `True`: Client can always use credit (normal behavior)
  - When `False`: Client can only use credit if they have available credit balance > 0
- **Use Case**: Restrict clients with poor payment history while still allowing them to use existing credit

### 2. `requires_note_for_credit` (Boolean, default: False)
- **Purpose**: Requires a mandatory note when processing credit transactions
- **Behavior**: 
  - When `True`: All credit transactions must include a note explaining the reason
  - When `False`: Notes are optional for credit transactions
- **Use Case**: Audit trail for special credit arrangements or temporary credit extensions

## Validation Rules

### Mutual Exclusion
Both fields cannot be restrictive simultaneously:
- `can_pay_with_credit = False` AND `requires_note_for_credit = True` is **not allowed**
- This prevents conflicting constraints

## New Methods Added

### Client Model Methods

#### `can_use_credit_for_payment()`
```python
def can_use_credit_for_payment(self):
    """Check if client can use credit for payments"""
```
- Returns `True` if client can use credit, `False` otherwise
- Respects the `can_pay_with_credit` field and available credit balance

#### `requires_note_for_credit_payment()`
```python
def requires_note_for_credit_payment(self):
    """Check if client requires a note when making credit payments"""
```
- Returns `True` if note is required, `False` otherwise
- Simple wrapper for the `requires_note_for_credit` field

#### `validate_credit_payment(amount, note=None)`
```python
def validate_credit_payment(self, amount, note=None):
    """Validate if a credit payment can be processed"""
```
- Comprehensive validation for credit payments
- Returns dict with success status and error details
- Error codes: `CREDIT_DISABLED`, `INSUFFICIENT_CREDIT`, `NOTE_REQUIRED`

## Updated Methods

### `can_afford_order(order_amount)`
- Now respects credit payment restrictions
- Only includes available credit in calculation if client can use credit

### `process_order_payment(order_amount, preferred_method='auto', order=None, user=None, credit_note=None)`
- Added `credit_note` parameter for required notes
- Validates credit usage before processing
- Returns appropriate error messages for different restriction scenarios

### `create_payment_for_order(order, payment_method='auto', user=None, credit_note=None)`
- Added `credit_note` parameter that gets passed through to payment processing

## Usage Examples

### Example 1: Client with Credit Disabled
```python
client = Client.objects.get(id=1)
client.can_pay_with_credit = False
client.credit_limit = 1000.00
client.current_debt = 1000.00  # No available credit
client.save()

# This client cannot use credit for new purchases
result = client.validate_credit_payment(100.00)
# Returns: {'success': False, 'error_code': 'CREDIT_DISABLED'}
```

### Example 2: Client Requiring Notes
```python
client = Client.objects.get(id=2)
client.requires_note_for_credit = True
client.save()

# Without note - fails
result = client.validate_credit_payment(100.00)
# Returns: {'success': False, 'error_code': 'NOTE_REQUIRED'}

# With note - succeeds
result = client.validate_credit_payment(100.00, note="Emergency delivery")
# Returns: {'success': True}
```

### Example 3: Processing Order Payment
```python
# For client requiring notes
result = client.process_order_payment(
    order_amount=250.00,
    preferred_method='credit',
    order=order_obj,
    user=request.user,
    credit_note="Approved by manager for emergency delivery"
)
```

## Database Migration
- Migration file: `clients/migrations/0012_client_can_pay_with_credit_and_more.py`
- Adds both boolean fields with appropriate defaults
- Safe to apply on existing databases

## UI Integration Recommendations

### 1. Payment Method Selection
```javascript
// Hide credit option if client can't use credit
if (!client.can_use_credit_for_payment && client.available_credit <= 0) {
    hidePaymentMethod('credit');
}
```

### 2. Note Requirement Handling
```javascript
// Show note field if required for credit payments
if (paymentMethod === 'credit' && client.requires_note_for_credit) {
    showRequiredField('credit_note');
}
```

### 3. Order Affordability Check
```javascript
// Check if client can afford order before showing payment options
if (!client.can_afford_order(orderTotal)) {
    showInsufficientFundsMessage();
}
```

## Error Handling

The implementation provides clear error codes for different scenarios:

- **CREDIT_DISABLED**: Client cannot use credit at this time
- **INSUFFICIENT_CREDIT**: Not enough credit limit available
- **NOTE_REQUIRED**: Must provide a note for credit transactions

## Testing

All functionality has been tested including:
- Default field values
- Validation rules (mutual exclusion)
- Credit payment availability checks
- Note requirement validation
- Order affordability calculations
- Payment processing with various scenarios

## Next Steps

1. **Update Admin Interface**: Add the new fields to Django admin
2. **Update Frontend**: Modify payment forms to handle credit restrictions and note requirements
3. **API Updates**: Update REST API endpoints to include new fields and validation
4. **Documentation**: Update user documentation to explain new credit controls
5. **Reporting**: Add reports to track credit usage patterns and note compliance