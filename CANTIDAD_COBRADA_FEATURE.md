# Cantidad Cobrada Feature Implementation

## Overview
This feature allows collecting more money than the order total, with the excess amount being automatically added to the client's balance for future use.

## How It Works

### 1. Order Form Enhancement
- Added "Cantidad Cobrada" (Amount Charged) field to both desktop and mobile order forms
- Field is pre-filled with the order total amount
- Users can override this amount to collect more money

### 2. Validation Rules
- **Minimum amount**: Cannot be less than the order total
- **Real-time validation**: Shows alerts and validation messages as user types
- **Cross-platform sync**: Desktop and mobile inputs stay synchronized

### 3. Balance Addition Logic
- **When cantidad_cobrada > order_total**: Excess amount is added to client balance
- **Transaction type**: Uses `added_in_order` transaction type
- **Audit trail**: Complete record with order reference and user attribution

### 4. User Interface Features

#### Desktop View
- Input field in the Payment Method card
- Real-time alert showing excess amount
- Color-coded validation feedback

#### Mobile View  
- Compact input in the fixed bottom summary
- Mobile-optimized alert messages
- Touch-friendly interface

#### Validation Alerts
- **Invalid (< order total)**: Red border, error message
- **Valid (= order total)**: No special styling
- **Excess (> order total)**: Blue info alert: "Vas a agregar $X.XX al saldo del cliente"

### 5. Backend Processing

#### Payment Creation Endpoint (`/payments/create/`)
```python
# Validates cantidad_cobrada
if cantidad_cobrada < order_total:
    return error

# Updates order record
order.cantidad_cobrada = cantidad_cobrada

# Adds excess to client balance
if cantidad_cobrada > order_total:
    excess = cantidad_cobrada - order_total
    client.add_balance(
        amount=excess,
        transaction_type='added_in_order',
        description=f'Saldo agregado en venta - Orden #{order.id}',
        reference_order=order
    )
```

#### Database Changes
- **Order model**: Added `cantidad_cobrada` field (nullable decimal)
- **BalanceTransaction**: Uses existing `added_in_order` transaction type
- **Migration**: `0008_order_cantidad_cobrada.py`

### 6. Success Feedback
After successful order completion, users see:
- Standard payment confirmation
- **If excess collected**: Additional panel showing:
  - Amount added to balance
  - Breakdown of amounts (cobrado vs total)
  - Client's new balance total

## Example Usage Scenarios

### Scenario 1: Exact Payment
- Order total: $100.00
- Cantidad cobrada: $100.00
- Result: Normal payment, no balance addition

### Scenario 2: Collecting Extra for Future Orders
- Order total: $100.00
- Cantidad cobrada: $150.00
- Result: 
  - Payment processed for $100.00
  - $50.00 added to client balance
  - BalanceTransaction created with type `added_in_order`

### Scenario 3: Invalid Amount
- Order total: $100.00
- Cantidad cobrada: $80.00
- Result: Validation error prevents submission

## Technical Implementation Details

### Files Modified
1. **orders/models.py**: Added `cantidad_cobrada` field to Order model
2. **orders/forms.py**: Created OrderForm with validation
3. **orders/templates/create_order.html**: Added UI fields and JavaScript validation
4. **payment/views.py**: Enhanced create_payment view with balance logic
5. **orders/migrations/0008_order_cantidad_cobrada.py**: Database migration

### JavaScript Functions
- `validateCantidadCobrada()`: Real-time validation and alert management
- Enhanced `handleFinishOrder()`: Includes cantidad_cobrada in payment request
- Cross-platform input synchronization

### Database Schema
```sql
-- New field in orders_order table
ALTER TABLE orders_order ADD COLUMN cantidad_cobrada DECIMAL(10,2) NULL;
```

### Transaction Audit Trail
Every excess amount creates a BalanceTransaction record:
- **Type**: `added_in_order`
- **Description**: "Saldo agregado en venta - Orden #123"
- **Reference**: Links to the order
- **User**: Records who processed the order
- **Notes**: Includes breakdown of amounts

## Benefits
1. **Cash Flow Management**: Collect prepayments for future orders
2. **Customer Convenience**: Clients can "load up" their account balance
3. **Complete Audit Trail**: Every transaction is recorded and traceable
4. **User-Friendly**: Clear validation and feedback throughout the process
5. **Mobile-Friendly**: Works seamlessly on tablets and phones

## Integration with Existing Balance System
- Uses existing `Client.add_balance()` method
- Leverages established BalanceTransaction audit system
- Maintains consistency with other balance operations
- Supports all existing balance history and reporting features