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

        const invoiceId = getBillingRecordId();
        const refreshes = Array.from(orderSelects).map((select) => {
            const preservedValue = getPreservedValue(select);
            return fetchBillableOrdersForClient(clientId, invoiceId, preservedValue)
                .then((orders) => {
                    populateOrderSelect(select, orders, preservedValue);
                });
        });

        Promise.all(refreshes)
            .then(() => {
                console.log("Updated", orderSelects.length, "order selects for client", clientId);
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
                            fetchBillableOrdersForClient(clientSelect.value, getBillingRecordId(), null)
                                .then(orders => {
                                    populateOrderSelect(newOrderSelect, orders, null);
                                    })
                                    .catch(err => {
                                        console.error("Error loading orders for new row:", err);
                                        clearOrderSelect(newOrderSelect, true);
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
    function fetchBillableOrdersForClient(clientId, invoiceId, includeOrderId) {
        const params = new URLSearchParams();
        if (invoiceId) {
            params.set("invoice_id", invoiceId);
        }
        if (includeOrderId) {
            params.set("include_order_id", includeOrderId);
        }

        // Use InvoiceAdmin endpoint that powers inline rows.
        const queryString = params.toString();
        const url = `/admin/billing/invoice/invoiceable-orders/${clientId}/${queryString ? `?${queryString}` : ""}`;
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

    function getPreservedValue(selectElement) {
        return selectElement.value || selectElement.dataset.initialValue || null;
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
        const preservedOptionText = valueToPreserve ? getOptionText(selectElement, valueToPreserve) : null;
        
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

        // If preserved value isn't present in response, keep the visible option
        // to avoid losing the current row selection.
        if (valueToPreserve && !foundPreservedValue) {
            if (preservedOptionText) {
                const option = document.createElement("option");
                option.value = valueToPreserve;
                option.textContent = preservedOptionText;
                selectElement.appendChild(option);
            }
        }

        // Restore selection
        if (valueToPreserve) {
            selectElement.value = valueToPreserve;
        }

        console.log("Populated select with", orders.length, "orders, preserved value:", valueToPreserve);
    }

    function getOptionText(selectElement, value) {
        const option = Array.from(selectElement.options).find((opt) => String(opt.value) === String(value));
        return option ? option.textContent : null;
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
