# Manual Balance Addition Guide

## 🎯 How to Add Balance to Clients in Django Admin

### Step-by-Step Instructions

#### **Method 1: Single Client Balance Addition**

1. **Navigate to Admin Panel**
   - Go to your Django admin: `http://localhost:8000/admin/`
   - Login with your admin credentials

2. **Access Clients Section**
   - Click on **"Clients"** in the main admin panel
   - You'll see the list of all clients

3. **Select Client**
   - Find the client you want to add balance to
   - **Check the checkbox** next to their name (left column)

4. **Use Admin Action**
   - Look at the top of the client list
   - Find the **"Action"** dropdown menu
   - You should see: **"Agregar saldo a clientes seleccionados"**
   - Select this option and click **"Go"**

5. **Fill the Form**
   - You'll be redirected to a form with fields:
     - **Client**: Pre-selected
     - **Amount**: Enter the amount to add (e.g., 100.00)
     - **Transaction Type**: Choose from dropdown (deposit, adjustment, etc.)
     - **Description**: Brief description (e.g., "Manual balance addition")
     - **Notes**: Detailed reason (e.g., "Client paid cash, adding to account")

6. **Submit**
   - Click **"Save"** 
   - You'll see a success message with the new balance
   - Client's balance will be updated immediately

#### **Method 2: Bulk Balance Addition (Multiple Clients)**

1. **Select Multiple Clients**
   - Check multiple client checkboxes
   - Use the same action: **"Agregar saldo a clientes seleccionados"**
   - This will automatically redirect to bulk deposit form

2. **Fill Bulk Form**
   - **Clients**: Multi-select the clients (pre-populated)
   - **Amount**: Same amount for all clients
   - **Description**: Bulk description
   - **Notes**: Reason for bulk addition

#### **Method 3: Credit Management**

1. **Select Single Client**
   - Check one client checkbox
   - Use action: **"Gestionar crédito del cliente seleccionado"**

2. **Choose Credit Operation**
   - **Change Credit Limit**: Increase/decrease credit limit
   - **Pay Debt**: Reduce client's debt
   - **Apply Adjustment**: Manual debt adjustments

## 🔍 What You Should See

### In Client List View:
- **Balance column**: Shows current balance
- **Current debt column**: Shows debt amount  
- **Available credit column**: Shows available credit
- **Action dropdown**: Contains the balance/credit actions

### In Client Detail View:
- **Financial Status section**: Color-coded balance and debt display
- **Balance and Credit section**: Shows current financial state

### After Adding Balance:
- **Success message**: "Saldo agregado exitosamente. [Client] ahora tiene $[amount] de saldo."
- **Updated balance**: Visible immediately in client list
- **Transaction record**: Created in BalanceTransaction admin

## 🚨 Troubleshooting

### If you don't see the actions:
1. **Check permissions**: Make sure you're logged in as admin/staff
2. **Refresh page**: Sometimes browser cache needs refresh
3. **Check client selection**: Must select at least one client

### If the form doesn't appear:
1. **Verify URL**: Should redirect to `/admin/clients/client/add-balance/`
2. **Check templates**: Templates should be in `clients/templates/admin/clients/`
3. **Django messages**: Look for error messages at the top of the page

### Direct URLs (if actions don't work):
- Add Balance: `http://localhost:8000/admin/clients/client/add-balance/`
- Add Credit: `http://localhost:8000/admin/clients/client/add-credit/`
- Bulk Deposit: `http://localhost:8000/admin/clients/client/bulk-deposit/`

## 📊 Transaction History

After adding balance, you can view the complete history:
1. Go to **"Balance transactions"** in admin
2. Filter by client name
3. See all balance changes with:
   - Date and time
   - Amount added/deducted
   - Balance before/after
   - Who made the change
   - Detailed notes

## 🎯 Example Workflow

**Scenario**: Client "Juan Pérez" paid $500 cash, need to add to his account

1. Go to Clients → Check "Juan Pérez" → Select "Agregar saldo" action
2. Fill form:
   - Amount: 500.00
   - Type: Deposit
   - Description: "Cash payment received"
   - Notes: "Client paid $500 cash on 2025-10-03 for future orders"
3. Submit → Success message shows new balance
4. Transaction automatically recorded with `[MANUAL]` prefix

This creates a complete audit trail showing exactly when and why the balance was added.