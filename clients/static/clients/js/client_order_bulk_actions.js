(function () {
  "use strict";

  class ReceiptBundleModal {
    constructor(getSelectedOrders) {
      this.getSelectedOrders = getSelectedOrders;
      this.openButton = document.getElementById("open-receipt-bundle-modal");
      this.form = document.getElementById("receipt-bundle-form");
      this.currentOrders = [];
    }

    init() {
      if (!this.openButton || !this.form) {
        return false;
      }
      this.contactSelect = document.getElementById("receipt-bundle-contact");
      this.recipientName = document.getElementById("receipt-bundle-recipient-name");
      this.recipientEmail = document.getElementById("receipt-bundle-recipient-email");
      this.availableCount = document.getElementById("receipt-bundle-available-count");
      this.availableList = document.getElementById("receipt-bundle-available-orders");
      this.missingSection = document.getElementById("receipt-bundle-missing-section");
      this.missingList = document.getElementById("receipt-bundle-missing-orders");
      this.resultAlert = document.getElementById("receipt-bundle-result");
      this.sendButton = document.getElementById("send-receipt-bundle");

      this.selectFirstContactWithEmail();
      this.contactSelect.addEventListener("change", () => this.fillRecipientFromContact());
      this.form.addEventListener("submit", (event) => this.handleSubmit(event));
      return true;
    }

    selectFirstContactWithEmail() {
      const match = Array.from(this.contactSelect.options).find((opt) => opt.dataset.email);
      if (match) {
        this.contactSelect.value = match.value;
        this.fillRecipientFromContact();
      }
    }

    fillRecipientFromContact() {
      const option = this.contactSelect.options[this.contactSelect.selectedIndex];
      this.recipientName.value = option ? option.dataset.name || "" : "";
      this.recipientEmail.value = option ? option.dataset.email || "" : "";
    }

    fillOrderList(list, orders) {
      list.replaceChildren();
      orders.forEach((checkbox) => {
        const item = document.createElement("li");
        item.textContent = `Pedido #${checkbox.value}`;
        list.appendChild(item);
      });
    }

    showResult(message, tone) {
      this.resultAlert.className = `pg-alert pg-alert-${tone} pg-mb-0`;
      this.resultAlert.textContent = message;
    }

    resetResult() {
      this.resultAlert.className = "pg-alert pg-d-none pg-mb-0";
      this.resultAlert.textContent = "";
    }

    open() {
      this.currentOrders = this.getSelectedOrders();
      const available = this.currentOrders.filter((cb) => cb.dataset.hasReceipt === "true");
      const missing = this.currentOrders.filter((cb) => cb.dataset.hasReceipt !== "true");

      this.availableCount.textContent = String(available.length);
      this.fillOrderList(this.availableList, available);
      this.fillOrderList(this.missingList, missing);
      this.missingSection.classList.toggle("pg-d-none", missing.length === 0);
      this.sendButton.disabled = available.length === 0;
      this.resetResult();

      if (!available.length) {
        this.showResult("Ninguno de los pedidos seleccionados tiene un recibo firmado.", "warning");
      }
      this.openButton.click();
    }

    async handleSubmit(event) {
      event.preventDefault();
      if (!this.form.reportValidity() || this.sendButton.disabled) {
        return;
      }

      const formData = new FormData(this.form);
      this.currentOrders.forEach((cb) => formData.append("orders", cb.value));
      this.sendButton.disabled = true;
      this.resetResult();

      try {
        const response = await fetch(this.form.dataset.sendUrl, {
          method: "POST",
          body: formData,
          headers: { "X-Requested-With": "XMLHttpRequest" },
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok || !data.success) {
          throw new Error(data.message || "No se pudieron enviar los recibos.");
        }
        this.showResult(data.message, "success");
      } catch (error) {
        this.showResult(error.message || "No se pudieron enviar los recibos.", "danger");
      } finally {
        this.sendButton.disabled = false;
      }
    }
  }

  class ClientOrderSelectionBar {
    constructor() {
      this.paymentForm = document.getElementById("selected-orders-payment-form");
      this.invoiceForm = document.getElementById("selected-orders-invoice-form");
      this.bar = document.getElementById("client-order-selection-bar");
      this.countEl = document.getElementById("client-order-selected-count");
      this.totalEl = document.getElementById("client-order-selected-total");
      this.selectAll = document.getElementById("select-all-client-orders");
      this.clearButton = document.getElementById("clear-client-order-selection");
      this.checkboxes = Array.from(document.querySelectorAll(".client-order-bulk-checkbox"));
      this.receiptModal = new ReceiptBundleModal(() => this.selectedOrders());
    }

    init() {
      if (!this.paymentForm || !this.bar || !this.checkboxes.length) {
        return;
      }
      this.hasReceiptModal = this.receiptModal.init();
      this.checkboxes.forEach((cb) => cb.addEventListener("change", () => this.update()));

      if (this.selectAll) {
        this.selectAll.addEventListener("change", () => this.toggleAll(this.selectAll.checked));
      }
      if (this.clearButton) {
        this.clearButton.addEventListener("click", () => this.toggleAll(false));
      }

      this.bar.querySelectorAll("[data-bulk-action]").forEach((btn) => {
        btn.addEventListener("click", () => this.runAction(btn.dataset.bulkAction));
      });
      this.update();
    }

    selectedOrders() {
      return this.checkboxes.filter((cb) => cb.checked);
    }

    toggleAll(checked) {
      this.checkboxes.forEach((cb) => {
        cb.checked = checked;
      });
      this.update();
    }

    update() {
      const selected = this.selectedOrders();
      const total = selected.reduce((sum, cb) => sum + (parseFloat(cb.dataset.orderTotal) || 0), 0);

      this.bar.classList.toggle("pg-d-none", selected.length === 0);
      if (this.countEl) this.countEl.textContent = String(selected.length);
      if (this.totalEl) this.totalEl.textContent = `$${total.toFixed(2)}`;

      if (this.selectAll) {
        this.selectAll.checked = selected.length === this.checkboxes.length;
        this.selectAll.indeterminate =
          selected.length > 0 && selected.length < this.checkboxes.length;
      }
    }

    submitInvoiceForm() {
      if (!this.invoiceForm) {
        return;
      }
      this.invoiceForm.querySelectorAll("[data-selected-order-id]").forEach((el) => el.remove());
      this.selectedOrders().forEach((cb) => {
        const input = document.createElement("input");
        input.type = "hidden";
        input.name = "orders";
        input.value = cb.value;
        input.dataset.selectedOrderId = "true";
        this.invoiceForm.appendChild(input);
      });
      this.invoiceForm.requestSubmit();
    }

    runAction(action) {
      if (!this.selectedOrders().length) {
        return;
      }
      if (action === "pay") {
        this.paymentForm.requestSubmit();
      } else if (action === "create_invoice") {
        this.submitInvoiceForm();
      } else if (action === "send_receipts" && this.hasReceiptModal) {
        this.receiptModal.open();
      }
    }
  }

  class ClientOrderCancelAction {
    constructor(csrfToken) {
      this.csrfToken = csrfToken;
    }

    init() {
      document.querySelectorAll(".client-order-cancel-action").forEach((button) => {
        button.addEventListener("click", () => this.cancel(button));
      });
    }

    async cancel(button) {
      const confirmed = window.confirm(
        "¿Desea cancelar este pedido? El pedido se marcará como cancelado y se revertirán los movimientos internos cuando aplique."
      );
      if (!confirmed) {
        return;
      }

      button.disabled = true;
      try {
        const response = await fetch(button.dataset.cancelUrl, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-CSRFToken": this.csrfToken,
          },
          body: JSON.stringify({}),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok || !data.success) {
          const fallback = data.review_required
            ? "La cancelación requiere revisión de administración."
            : "No se pudo cancelar el pedido.";
          throw new Error(data.error || fallback);
        }
        window.alert(data.message || "Pedido cancelado correctamente.");
        window.location.reload();
      } catch (error) {
        button.disabled = false;
        window.alert(error.message || "No se pudo cancelar el pedido.");
      }
    }
  }

  class ClientDetailTabsSync {
    init() {
      document.querySelectorAll("#client-detail-tabs [data-tab-key]").forEach((tab) => {
        tab.addEventListener("click", () => this.rememberTab(tab.dataset.tabKey));
      });
    }

    rememberTab(tabKey) {
      if (!tabKey || !window.history || !window.history.replaceState) {
        return;
      }
      const url = new URL(window.location.href);
      url.searchParams.set("tab", tabKey);
      window.history.replaceState(null, "", url.toString());
    }
  }

  class ClientDetailPage {
    constructor(csrfToken) {
      this.selectionBar = new ClientOrderSelectionBar();
      this.cancelAction = new ClientOrderCancelAction(csrfToken);
      this.tabsSync = new ClientDetailTabsSync();
    }

    init() {
      this.selectionBar.init();
      this.cancelAction.init();
      this.tabsSync.init();
    }
  }

  window.ClientDetailPage = ClientDetailPage;
})();
