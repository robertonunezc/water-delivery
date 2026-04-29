(function () {
  "use strict";

  // Wait for DOM to be ready
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  function init() {
    const invoiceSelect = document.getElementById("id_invoice");
    const orderSelect = document.getElementById("id_order");

    if (!invoiceSelect || !orderSelect) {
      return; // not on InvoiceOrderLink admin form
    }

    if (orderSelect.value) {
      orderSelect.dataset.initialValue = orderSelect.value;
    }

    const handleInvoiceChange = (invoiceId) => {
      if (!invoiceId) {
        clearOrderSelect(orderSelect);
        return;
      }

      const preserveValue = orderSelect.value || orderSelect.dataset.initialValue || null;

      fetchClientId(invoiceId)
        .then((clientId) => {
          if (clientId) {
            return fetchBillableOrders(clientId, invoiceId, preserveValue);
          }
          return [];
        })
        .then((orders) => {
          populateOrderSelect(orderSelect, orders, preserveValue);
        })
        .catch((error) => {
          console.error("Error loading billable orders:", error);
          clearOrderSelect(orderSelect);
        });
    };

    // Listen for native change events on invoice select
    invoiceSelect.addEventListener("change", function () {
      handleInvoiceChange(this.value);
    });

    // Load billable orders immediately if a record is preselected
    if (invoiceSelect.value) {
      handleInvoiceChange(invoiceSelect.value);
    }
  }

  function fetchClientId(invoiceId) {
    const url = `/admin/invoice/invoiceorderlink/invoice/${invoiceId}/client/`;
    console.log("fetchClientId: requesting", url);

    return fetch(url, {
      headers: {
        "X-Requested-With": "XMLHttpRequest",
      },
      credentials: "same-origin",
    })
      .then((response) => {
        console.log("fetchClientId response status:", response.status);
        if (!response.ok) {
          throw new Error("Failed to fetch client ID");
        }
        return response.json();
      })
      .then((data) => {
        console.log("fetchClientId response data:", data);
        return data.client_id;
      });
  }

  function fetchBillableOrders(clientId, invoiceId, includeOrderId) {
    let url = `/admin/invoice/invoiceorderlink/invoiceable-orders/${clientId}/`;
    const params = new URLSearchParams();

    if (invoiceId) {
      params.set("invoice_id", invoiceId);
    }
    if (includeOrderId) {
      params.set("include_order_id", includeOrderId);
    }
    if (params.toString()) {
      url += `?${params.toString()}`;
    }
    
    console.log("fetchBillableOrders: requesting", url);

    return fetch(url, {
      headers: {
        "X-Requested-With": "XMLHttpRequest",
      },
      credentials: "same-origin",
    })
      .then((response) => {
        console.log("fetchBillableOrders response status:", response.status);
        if (!response.ok) {
          throw new Error("Failed to fetch billable orders");
        }
        return response.json();
      })
      .then((data) => {
        console.log("fetchBillableOrders response data:", data);
        return data.orders || [];
      });
  }

  function clearOrderSelect(selectElement) {
    // Keep only the empty option
    while (selectElement.options.length > 1) {
      selectElement.remove(1);
    }
    selectElement.selectedIndex = 0;
  }

  function populateOrderSelect(selectElement, orders, preserveValue) {
    console.log("populateOrderSelect called with", orders.length, "orders");

    const valueToPreserve = preserveValue || selectElement.dataset.initialValue || null;
    const preservedText = valueToPreserve ? getOptionText(selectElement, valueToPreserve) : null;
    
    // Clear existing options except the first (empty) one
    clearOrderSelect(selectElement);

    let foundPreservedValue = false;

    // Add new options
    orders.forEach((order) => {
      const option = document.createElement("option");
      option.value = order.id;
      option.textContent = order.display || `Order #${order.id}`;
      selectElement.appendChild(option);
      console.log("Added option:", order.id, option.textContent);

      if (String(order.id) === String(valueToPreserve)) {
        foundPreservedValue = true;
      }
    });

    if (valueToPreserve && !foundPreservedValue && preservedText) {
      const option = document.createElement("option");
      option.value = valueToPreserve;
      option.textContent = preservedText;
      selectElement.appendChild(option);
    }

    if (valueToPreserve) {
      selectElement.value = valueToPreserve;
    }

    // If only one order is available, auto-select it
    if (orders.length === 1 && !valueToPreserve) {
      console.log("Auto-selecting single order");
      selectElement.selectedIndex = 1;
    }
    
    console.log("populateOrderSelect complete. Select now has", selectElement.options.length, "options");
  }

  function getOptionText(selectElement, value) {
    const option = Array.from(selectElement.options).find((opt) => String(opt.value) === String(value));
    return option ? option.textContent : null;
  }
})();
