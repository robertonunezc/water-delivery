// Enhanced Orders Admin JavaScript

document.addEventListener('DOMContentLoaded', function() {
    // Add status-based row classes for better visual distinction
    addStatusRowClasses();
    
    // Enhance inline formsets
    enhanceInlineFormsets();
    
    // Add quick calculation features
    addQuickCalculations();
    
    // Add confirmation dialogs for bulk actions
    addActionConfirmations();
    
    // Auto-refresh payment status
    autoRefreshPaymentStatus();
});

function addStatusRowClasses() {
    // Add CSS classes to table rows based on order status
    const rows = document.querySelectorAll('#result_list tbody tr');
    rows.forEach(row => {
        const statusCell = row.querySelector('td:nth-child(3)'); // Assuming status is 3rd column
        if (statusCell) {
            const statusText = statusCell.textContent.toLowerCase();
            if (statusText.includes('pendiente')) {
                row.classList.add('status-pending');
            } else if (statusText.includes('completado')) {
                row.classList.add('status-completed');
            } else if (statusText.includes('cancelado')) {
                row.classList.add('status-cancelled');
            }
        }
    });
}

function enhanceInlineFormsets() {
    // Add calculations to OrderProduct inlines
    const inlineRows = document.querySelectorAll('.dynamic-orders_orderproduct_set');
    inlineRows.forEach(row => {
        const quantityField = row.querySelector('input[name*="quantity"]');
        const priceField = row.querySelector('input[name*="unit_price"]');
        const totalDisplay = row.querySelector('.total-display');
        
        if (quantityField && priceField) {
            [quantityField, priceField].forEach(field => {
                field.addEventListener('input', function() {
                    calculateRowTotal(row, quantityField, priceField, totalDisplay);
                });
            });
        }
    });
}

function calculateRowTotal(row, quantityField, priceField, totalDisplay) {
    const quantity = parseFloat(quantityField.value) || 0;
    const price = parseFloat(priceField.value) || 0;
    const total = quantity * price;
    
    if (totalDisplay) {
        totalDisplay.textContent = `$${total.toFixed(2)}`;
        totalDisplay.style.fontWeight = 'bold';
        totalDisplay.style.color = total > 0 ? '#28a745' : '#6c757d';
    }
    
    // Update order total if needed
    updateOrderTotal();
}

function addQuickCalculations() {
    // Add a total calculator widget
    const changeForm = document.querySelector('.change-form');
    if (changeForm) {
        const calculator = document.createElement('div');
        calculator.className = 'order-calculator';
        calculator.innerHTML = `
            <div style="background: #f8f9fa; padding: 15px; border-radius: 5px; margin: 10px 0;">
                <h4 style="margin-top: 0;">Calculadora de Pedido</h4>
                <div id="calc-total" style="font-size: 1.2em; font-weight: bold; color: #28a745;">
                    Total: $0.00
                </div>
                <div id="calc-items" style="color: #6c757d;">
                    0 items
                </div>
                <button type="button" id="recalculate" class="btn btn-sm btn-secondary" style="margin-top: 10px;">
                    Recalcular
                </button>
            </div>
        `;
        
        const totalAmountField = document.querySelector('input[name="total_amount"]');
        if (totalAmountField && totalAmountField.parentNode) {
            totalAmountField.parentNode.appendChild(calculator);
            
            // Add recalculate functionality
            document.getElementById('recalculate').addEventListener('click', updateOrderTotal);
            
            // Auto-calculate on page load
            updateOrderTotal();
        }
    }
}

function updateOrderTotal() {
    const inlineRows = document.querySelectorAll('.dynamic-orders_orderproduct_set:not(.empty-form)');
    let totalAmount = 0;
    let totalItems = 0;
    
    inlineRows.forEach(row => {
        if (row.querySelector('input[name*="DELETE"]')?.checked) {
            return; // Skip deleted rows
        }
        
        const quantity = parseFloat(row.querySelector('input[name*="quantity"]')?.value) || 0;
        const price = parseFloat(row.querySelector('input[name*="unit_price"]')?.value) || 0;
        
        totalAmount += quantity * price;
        totalItems += quantity;
    });
    
    // Update calculator display
    const calcTotal = document.getElementById('calc-total');
    const calcItems = document.getElementById('calc-items');
    
    if (calcTotal) {
        calcTotal.textContent = `Total: $${totalAmount.toFixed(2)}`;
    }
    
    if (calcItems) {
        calcItems.textContent = `${totalItems} items`;
    }
    
    // Update the actual total amount field
    const totalAmountField = document.querySelector('input[name="total_amount"]');
    if (totalAmountField) {
        totalAmountField.value = totalAmount.toFixed(2);
        totalAmountField.style.backgroundColor = totalAmount > 0 ? '#d1edda' : '#fff3cd';
    }
}

function addActionConfirmations() {
    // Add confirmation dialogs for bulk actions
    const actionSelect = document.querySelector('select[name="action"]');
    const actionButton = document.querySelector('button[name="index"]');
    
    if (actionSelect && actionButton) {
        actionButton.addEventListener('click', function(e) {
            const selectedAction = actionSelect.value;
            const checkedItems = document.querySelectorAll('input[name="_selected_action"]:checked');
            
            if (checkedItems.length === 0) {
                alert('Por favor, selecciona al menos un pedido.');
                e.preventDefault();
                return;
            }
            
            let confirmMessage = '';
            switch (selectedAction) {
                case 'mark_as_completed':
                    confirmMessage = `¿Estás seguro de que quieres marcar ${checkedItems.length} pedido(s) como completados?`;
                    break;
                case 'mark_as_cancelled':
                    confirmMessage = `¿Estás seguro de que quieres marcar ${checkedItems.length} pedido(s) como cancelados?`;
                    break;
                case 'mark_as_pending':
                    confirmMessage = `¿Estás seguro de que quieres marcar ${checkedItems.length} pedido(s) como pendientes?`;
                    break;
                default:
                    return; // No confirmation needed for other actions
            }
            
            if (!confirm(confirmMessage)) {
                e.preventDefault();
            }
        });
    }
}

function autoRefreshPaymentStatus() {
    // Auto-refresh payment status indicators
    const paymentCells = document.querySelectorAll('td[class*="payment-status"]');
    
    paymentCells.forEach(cell => {
        // Add a refresh button to payment cells
        if (!cell.querySelector('.refresh-payment')) {
            const refreshBtn = document.createElement('button');
            refreshBtn.className = 'refresh-payment';
            refreshBtn.innerHTML = '🔄';
            refreshBtn.style.cssText = 'background: none; border: none; cursor: pointer; margin-left: 5px; opacity: 0.6;';
            refreshBtn.title = 'Actualizar estado de pago';
            
            refreshBtn.addEventListener('click', function(e) {
                e.preventDefault();
                // Here you could implement AJAX to refresh payment status
                cell.style.opacity = '0.5';
                setTimeout(() => {
                    cell.style.opacity = '1';
                    // In a real implementation, you'd make an AJAX call here
                }, 500);
            });
            
            cell.appendChild(refreshBtn);
        }
    });
}

// Utility functions
function formatCurrency(amount) {
    return new Intl.NumberFormat('es-MX', {
        style: 'currency',
        currency: 'MXN'
    }).format(amount);
}

function showNotification(message, type = 'info') {
    const notification = document.createElement('div');
    notification.className = `alert alert-${type}`;
    notification.style.cssText = 'position: fixed; top: 20px; right: 20px; z-index: 9999; max-width: 300px;';
    notification.textContent = message;
    
    document.body.appendChild(notification);
    
    setTimeout(() => {
        notification.remove();
    }, 3000);
}

// Export functions for potential external use
window.OrdersAdminUtils = {
    updateOrderTotal,
    calculateRowTotal,
    formatCurrency,
    showNotification
};