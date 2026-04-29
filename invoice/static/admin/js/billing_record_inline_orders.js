/**
 * Dynamic order filtering for BillingOrder inline in BillingRecordAdmin.
 * 
 * When the user selects a client in the parent BillingRecord form,
 * this script filters the order dropdown in each BillingOrder inline row
 * to show only orders belonging to that client.
 */
(function () {
    "use strict";

    // Wait for DOM to be ready
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }

    function init() {
        // Find the client select in the parent BillingRecord form
        const clientSelect = document.getElementById("id_client");
        
        if (!clientSelect) {
            return; // Not on BillingRecord admin form
        }

        console.log("BillingRecord inline orders: initialized");

        // Initial load if client is already selected
        if (clientSelect.value) {
            updateAllInlineOrderSelects(clientSelect.value);
        }

        // Listen for client changes
        clientSelect.addEventListener("change", function () {
            console.log("Client changed to:", this.value);
            updateAllInlineOrderSelects(this.value);
        });

        // Handle dynamically added inline rows (when user clicks "Add another")
        observeNewInlineRows(clientSelect);
    }

    /**
     * Update all order select elements in inline forms
     */
    function updateAllInlineOrderSelects(clientId) {
        const orderSelects = document.querySelectorAll(
            '[id^="id_invoice_links-"][id$="-order"]'
        );

        console.log("Found", orderSelects.length, "order selects to update");

        if (!clientId) {
            // Clear all order selects and show placeholder if no client selected
            orderSelects.forEach(select => clearOrderSelect(select, true));
            return;
        }

        // Fetch billable orders for this client
        fetchBillableOrdersForClient(clientId)
            .then(orders => {
                console.log("Fetched", orders.length, "orders for client", clientId);
                orderSelects.forEach(select => {
                    const currentValue = select.value;
                    populateOrderSelect(select, orders, currentValue);
                });
            })
            .catch(error => {
                console.error("Error fetching orders:", error);
            });
    }

    /**
     * Observe for new inline rows being added dynamically
     */
    function observeNewInlineRows(clientSelect) {
        const inlineGroup = document.querySelector(".inline-group");
        if (!inlineGroup) return;

        const observer = new MutationObserver(function (mutations) {
            mutations.forEach(function (mutation) {
                mutation.addedNodes.forEach(function (node) {
                    if (node.nodeType === Node.ELEMENT_NODE) {
                        // Check if this is a new inline row with an order select
                        const newOrderSelect = node.querySelector
                            ? node.querySelector('[id^="id_invoice_links-"][id$="-order"]')
                            : null;
                        
                        if (newOrderSelect && clientSelect.value) {
                            console.log("New inline row added, updating order select");
                            fetchBillableOrdersForClient(clientSelect.value)
                                .then(orders => {
                                    populateOrderSelect(newOrderSelect, orders, null);
                                });
                        } else if (newOrderSelect && !clientSelect.value) {
                            clearOrderSelect(newOrderSelect, true);
                        }
                    }
                });
            });
        });

        observer.observe(inlineGroup, { childList: true, subtree: true });
    }

    /**
     * Fetch billable orders for a specific client
     */
    function fetchBillableOrdersForClient(clientId) {
        // For filtering, we might want to get the billing record ID if editing
        const billingRecordId = getBillingRecordId();
        let queryParam = billingRecordId ? `?invoice_id=${billingRecordId}` : "";

        // Use the Invoice admin's endpoint for inline context
        const url = `/admin/invoice/invoice/invoiceable-orders/${clientId}/${queryParam}`;
        console.log("Fetching billable orders from:", url);

        return fetch(url, {
            headers: {
                "X-Requested-With": "XMLHttpRequest",
            },
            credentials: "same-origin",
        })
            .then(response => {
                if (!response.ok) {
                    throw new Error("Failed to fetch billable orders");
                }
                return response.json();
            })
            .then(data => data.orders || []);
    }

    /**
     * Get the current BillingRecord ID if editing an existing record
     */
    function getBillingRecordId() {
        // Check URL for object ID (e.g., /admin/invoice/invoice/123/change/)
        const match = window.location.pathname.match(/\/invoice\/(\d+)\/change\//);
        return match ? match[1] : null;
    }

    /**
     * Clear all options from select except the empty first one.
     * @param {HTMLSelectElement} selectElement
     * @param {boolean} showNoClientMessage - show a disabled placeholder when no client is selected
     */
    function clearOrderSelect(selectElement, showNoClientMessage = false) {
        selectElement.innerHTML = "";

        const placeholder = document.createElement("option");
        placeholder.value = "";
        placeholder.textContent = showNoClientMessage
            ? "— Seleccione un cliente primero —"
            : "---------";
        placeholder.disabled = showNoClientMessage;
        selectElement.appendChild(placeholder);
        selectElement.selectedIndex = 0;
    }

    /**
     * Populate order select with filtered orders
     */
    function populateOrderSelect(selectElement, orders, preserveValue) {
        // Store any currently selected value that should be preserved
        // (for existing BillingOrders being edited)
        const valueToPreserve = preserveValue || selectElement.dataset.initialValue;
        
        // Get the empty option text
        const emptyOptionText = selectElement.options[0]
            ? selectElement.options[0].textContent
            : "---------";

        // Clear and rebuild
        selectElement.innerHTML = "";

        // Add empty option
        const emptyOption = document.createElement("option");
        emptyOption.value = "";
        emptyOption.textContent = emptyOptionText;
        selectElement.appendChild(emptyOption);

        // Track if we found the value to preserve
        let foundPreservedValue = false;

        // Add order options
        orders.forEach(order => {
            const option = document.createElement("option");
            option.value = order.id;
            option.textContent = order.display || `Order #${order.id} - ${order.order_date} - $${order.total_amount}`;
            selectElement.appendChild(option);

            if (String(order.id) === String(valueToPreserve)) {
                foundPreservedValue = true;
            }
        });

        // If the preserved value isn't in the new list but was set,
        // we might need to add it (for already-associated orders)
        if (valueToPreserve && !foundPreservedValue) {
            // The order might already be associated with this BillingOrder
            // In that case, we need to include it even though it's not "billable"
            // This is handled server-side in the form's queryset, but we need
            // to keep the option visible in JS
            const existingOption = Array.from(document.querySelectorAll(
                `option[value="${valueToPreserve}"]`
            )).find(opt => opt.closest('select') !== selectElement);
            
            if (existingOption) {
                const option = document.createElement("option");
                option.value = valueToPreserve;
                option.textContent = existingOption.textContent;
                selectElement.appendChild(option);
            }
        }

        // Restore selection
        if (valueToPreserve) {
            selectElement.value = valueToPreserve;
        }

        console.log("Populated select with", orders.length, "orders, preserved value:", valueToPreserve);
    }

    /**
     * Store initial values for existing inline forms on page load
     */
    function storeInitialValues() {
        const orderSelects = document.querySelectorAll(
            '[id^="id_invoice_links-"][id$="-order"]'
        );
        
        orderSelects.forEach(select => {
            if (select.value) {
                select.dataset.initialValue = select.value;
                console.log("Stored initial value for", select.id, ":", select.value);
            }
        });
    }

    // Also store initial values
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", storeInitialValues);
    } else {
        storeInitialValues();
    }
})();
