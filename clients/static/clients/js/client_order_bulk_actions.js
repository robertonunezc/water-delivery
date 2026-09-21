(function () {
  "use strict";

  function initializeClientOrderBulkActions() {
    const paymentForm = document.getElementById("selected-orders-payment-form");
    const actionSelect = document.getElementById("client-order-bulk-action");
    const applyButton = document.getElementById("apply-client-order-bulk-action");
    const selectAll = document.getElementById("select-all-client-orders");
    const orderCheckboxes = Array.from(
      document.querySelectorAll(".client-order-bulk-checkbox")
    );

    if (!paymentForm || !actionSelect || !applyButton || !orderCheckboxes.length) {
      return;
    }

    const selectedOrders = () => orderCheckboxes.filter((checkbox) => checkbox.checked);

    function updateControls() {
      const selectedCount = selectedOrders().length;
      applyButton.disabled = selectedCount === 0 || !actionSelect.value;

      if (selectAll) {
        selectAll.checked = selectedCount === orderCheckboxes.length;
        selectAll.indeterminate = selectedCount > 0 && selectedCount < orderCheckboxes.length;
      }
    }

    orderCheckboxes.forEach((checkbox) => {
      checkbox.addEventListener("change", updateControls);
    });
    actionSelect.addEventListener("change", updateControls);

    if (selectAll) {
      selectAll.addEventListener("change", function () {
        orderCheckboxes.forEach((checkbox) => {
          checkbox.checked = selectAll.checked;
        });
        updateControls();
      });
    }

    const receiptModal = initializeReceiptBundleModal(selectedOrders);
    applyButton.addEventListener("click", function () {
      if (actionSelect.value === "pay") {
        paymentForm.requestSubmit();
        return;
      }
      if (actionSelect.value === "send_receipts" && receiptModal) {
        receiptModal.open();
      }
    });

    updateControls();
  }

  function initializeReceiptBundleModal(selectedOrders) {
    const openButton = document.getElementById("open-receipt-bundle-modal");
    const form = document.getElementById("receipt-bundle-form");
    if (!openButton || !form) {
      return null;
    }

    const contactSelect = document.getElementById("receipt-bundle-contact");
    const recipientName = document.getElementById("receipt-bundle-recipient-name");
    const recipientEmail = document.getElementById("receipt-bundle-recipient-email");
    const availableCount = document.getElementById("receipt-bundle-available-count");
    const availableList = document.getElementById("receipt-bundle-available-orders");
    const missingSection = document.getElementById("receipt-bundle-missing-section");
    const missingList = document.getElementById("receipt-bundle-missing-orders");
    const resultAlert = document.getElementById("receipt-bundle-result");
    const sendButton = document.getElementById("send-receipt-bundle");
    let currentOrders = [];

    function fillRecipientFromContact() {
      const option = contactSelect.options[contactSelect.selectedIndex];
      recipientName.value = option ? option.dataset.name || "" : "";
      recipientEmail.value = option ? option.dataset.email || "" : "";
    }

    const firstContactWithEmail = Array.from(contactSelect.options).find(
      (option) => option.dataset.email
    );
    if (firstContactWithEmail) {
      contactSelect.value = firstContactWithEmail.value;
      fillRecipientFromContact();
    }
    contactSelect.addEventListener("change", fillRecipientFromContact);

    function fillOrderList(list, orders) {
      list.replaceChildren();
      orders.forEach((checkbox) => {
        const item = document.createElement("li");
        item.textContent = `Pedido #${checkbox.value}`;
        list.appendChild(item);
      });
    }

    function showResult(message, tone) {
      resultAlert.className = `pg-alert pg-alert-${tone} pg-mb-0`;
      resultAlert.textContent = message;
    }

    function resetResult() {
      resultAlert.className = "pg-alert pg-d-none pg-mb-0";
      resultAlert.textContent = "";
    }

    function prepareModal() {
      currentOrders = selectedOrders();
      const availableOrders = currentOrders.filter(
        (checkbox) => checkbox.dataset.hasReceipt === "true"
      );
      const missingOrders = currentOrders.filter(
        (checkbox) => checkbox.dataset.hasReceipt !== "true"
      );

      availableCount.textContent = String(availableOrders.length);
      fillOrderList(availableList, availableOrders);
      fillOrderList(missingList, missingOrders);
      missingSection.classList.toggle("pg-d-none", missingOrders.length === 0);
      sendButton.disabled = availableOrders.length === 0;
      resetResult();

      if (!availableOrders.length) {
        showResult(
          "Ninguno de los pedidos seleccionados tiene un recibo firmado.",
          "warning"
        );
      }
      openButton.click();
    }

    form.addEventListener("submit", async function (event) {
      event.preventDefault();
      if (!form.reportValidity() || sendButton.disabled) {
        return;
      }

      const formData = new FormData(form);
      currentOrders.forEach((checkbox) => formData.append("orders", checkbox.value));
      sendButton.disabled = true;
      resetResult();

      try {
        const response = await fetch(form.dataset.sendUrl, {
          method: "POST",
          body: formData,
          headers: { "X-Requested-With": "XMLHttpRequest" },
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok || !data.success) {
          throw new Error(data.message || "No se pudieron enviar los recibos.");
        }
        showResult(data.message, "success");
      } catch (error) {
        showResult(error.message || "No se pudieron enviar los recibos.", "danger");
      } finally {
        sendButton.disabled = false;
      }
    });

    return { open: prepareModal };
  }

  document.addEventListener("DOMContentLoaded", initializeClientOrderBulkActions);
})();
