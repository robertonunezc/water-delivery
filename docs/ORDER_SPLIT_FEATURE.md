# Order Split Feature

## Overview
The Order Split feature allows administrators to divide an existing order into two separate orders. This is useful when you need to separate products from a single order for billing, delivery, or organizational purposes.

## How It Works

### Access the Feature
1. Navigate to Django Admin → Orders → Orders
2. Select the order you want to split
3. In the order detail page, you'll see a "Dividir Orden" (Split Order) button in the "Acciones" section
4. Click the button to access the split order form

### Split Process
1. **Select Quantities**: For each product in the order, specify how many items you want to move to the new order
2. **Validation**: 
   - You must move at least one product to the new order
   - The original order must keep at least one product with quantity > 0
   - Cannot move more items than available for each product
3. **Submit**: Click "Dividir Orden" to complete the split

### What Happens During Split

#### Original Order
- Quantities are reduced by the amounts moved to the new order
- Total amount is recalculated based on remaining products
- If `cantidad_cobrada` exists, it's split proportionally
- Products with 0 remaining quantity are removed

#### New Order
- Created with the same client, status, and order date as the original
- Contains the products and quantities specified in the split form
- Total amount is calculated based on moved products
- Notes field indicates it was split from the original order (e.g., "Dividida de Orden #123")
- `cantidad_cobrada` is split proportionally if present in the original order

#### Split Record
- An `OrderSplit` record is created for tracking purposes
- Stores: source order, child order, split by (user), and timestamp
- Used for reporting and audit trail

### Split History
Each order displays its split history in the admin:
- **As Source**: Shows if the order was split into other orders (child orders)
- **As Child**: Shows if the order was created from another order (parent order)

This history is visible in the "Historial de Divisiones" section in the order detail page.

## Example

**Original Order #123:**
- 3 × Product A @ $10 = $30
- 4 × Product B @ $10 = $40
- **Total: $70**
- **Cantidad Cobrada: $70**

**Split Action:**
- Move 2 × Product A to new order
- Move 2 × Product B to new order

**Result:**

**Order #123 (Updated):**
- 1 × Product A @ $10 = $10
- 2 × Product B @ $10 = $20
- **Total: $30**
- **Cantidad Cobrada: $30** (proportionally split)

**New Order #124:**
- 2 × Product A @ $10 = $20
- 2 × Product B @ $10 = $20
- **Total: $40**
- **Cantidad Cobrada: $40** (proportionally split)
- **Notes: "Dividida de Orden #123"**

## Database Schema

### OrderSplit Model
```python
class OrderSplit(models.Model):
    source_order = ForeignKey to Order (original order)
    child_order = ForeignKey to Order (new order created)
    split_by = ForeignKey to User (who performed the split)
    notes = TextField (additional notes)
    created_at = DateTimeField (when the split occurred)
    updated_at = DateTimeField (auto-updated)
```

## Reports
The `OrderSplit` model can be used to generate reports on:
- How many times an order has been split
- Which orders were derived from other orders
- Split activity by user
- Timeline of order splitting operations

## Admin Interface

### OrderAdmin
- Added "split_order_button" readonly field showing the split button
- Added "split_history_display" readonly field showing split history
- Both appear in the order detail page

### OrderSplitAdmin
- View-only admin for tracking split records
- Cannot be manually created or deleted (except by superusers)
- Shows source and child orders with links
- Displays detailed summary of what was in each order after split

## Technical Notes

### Proportional Split of `cantidad_cobrada`
If the original order has a `cantidad_cobrada` value:
```python
proportion_original = original_total / (original_total + new_total)
proportion_new = new_total / (original_total + new_total)

original_order.cantidad_cobrada = original_cobrada * proportion_original
new_order.cantidad_cobrada = original_cobrada * proportion_new
```

### Transaction Safety
The split operation is wrapped in a database transaction (`@transaction.atomic`) to ensure data integrity. If any error occurs, all changes are rolled back.

### Validation Rules
1. At least one product must be moved to the new order
2. The original order must retain at least one product with quantity > 0
3. Cannot move more items than available for each product
4. Quantity to move must be >= 0 and <= available quantity

## Future Enhancements
Potential improvements for this feature:
- Ability to edit order date/status for the new order during split
- Option to automatically adjust payment records
- Bulk split operations for multiple orders
- Split order from order list view (action)
- Email notifications when orders are split
