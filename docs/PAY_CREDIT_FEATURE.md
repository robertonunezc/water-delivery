# Pay Credit Feature Implementation

## Overview
This document describes the implementation of the "Pay Credit" feature that allows users to manage client credit/debt transactions from the client table interface.

## Changes Made

### 1. URL Configuration (`clients/urls.py`)
- Added new URL pattern: `path('<int:pk>/pay-credit/', views.pay_credit, name='pay_credit')`
- This route handles the credit payment functionality for a specific client

### 2. View Function (`clients/views.py`)
- Added `pay_credit(request, pk)` view function
- Handles both GET and POST requests
- **GET**: Displays the form with client information pre-filled
- **POST**: Processes the credit transaction based on transaction type:
  - `limit_change`: Updates the client's credit limit
  - `payment`, `forgiveness`, `adjustment`, `correction`: Reduces client debt
  - `payment_from_balance`: Uses client's prepaid balance to pay debt
- Redirects to client detail page on success
- Shows appropriate success/error messages using Django messages framework

### 3. Template (`clients/templates/pay_credit.html`)
- New template for the pay credit interface
- Features:
  - Breadcrumb navigation
  - Client information display (balance, debt, credit limit, available credit)
  - Transaction form with dynamic field visibility
  - JavaScript to show/hide fields based on transaction type
  - Information card explaining transaction types
  - Bootstrap-styled responsive design
- Form includes:
  - Transaction type selector
  - Amount field (hidden for limit changes)
  - New credit limit field (only visible for limit changes)
  - Description field
  - Notes field (required, minimum 10 characters)

### 4. Client Table Update (`core/templates/includes/client_table.html`)
- Updated "Credito" button to link to the new pay_credit view
- Changed from `href="#"` to `href="{% url 'clients:pay_credit' item.pk %}"`
- Updated title attribute from "Facturar" to "Pagar Crédito"

## Features

### Transaction Types Supported
1. **Pago de deuda**: Client paid their outstanding debt (cash, transfer, etc.)
2. **Pago con Saldo**: Use client's prepaid balance to pay their debt
3. **Ajuste manual de deuda**: Manual debt adjustment for administrative reasons
4. **Condonación de deuda**: Debt forgiveness by special authorization
5. **Corrección**: Correction of a previous error
6. **Cambio de límite de crédito**: Modify the client's credit limit

### Validation
- Form validation ensures:
  - Amount is greater than zero
  - Notes have at least 10 characters
  - For debt payments, amount doesn't exceed current debt
  - For balance payments, client has sufficient balance
  - For limit changes, new limit is not less than current debt

### User Interface
- Clean, Bootstrap-based responsive design
- Color-coded badges for balance/debt status
- Dynamic form fields based on transaction type
- Clear transaction type descriptions
- Breadcrumb navigation for easy navigation

### Security
- Login required (`@login_required` decorator)
- Client selection is disabled in form (hidden field)
- All transactions are logged with user information
- Transaction history maintained for audit trail

## Usage

1. Navigate to the Clients list
2. Click the "Credito" button (red button with credit card icon) for the desired client
3. Select the transaction type
4. Enter the amount (or new credit limit for limit changes)
5. Provide description and detailed notes
6. Click "Procesar Transacción" to submit
7. View success message and updated client information

## Dependencies
- Existing `ManualCreditTransactionForm` in `clients/forms.py`
- Client model methods: `pay_debt()`, `pay_debt_from_balance()`, `update_credit_limit()`
- Django messages framework
- Bootstrap 5.x for styling
- Font Awesome for icons

## Notes
- All transactions are recorded in the `CreditTransaction` model
- Transactions cannot be deleted (enforced in admin)
- User who created the transaction is tracked
- Detailed notes are required for audit trail
