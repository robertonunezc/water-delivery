class PageConfig {
  constructor(root) {
    this.root = root;
    this.orderId = root.dataset.orderId;
    this.cancelOrderUrl = root.dataset.cancelOrderUrl || '';
    this.clientBalance = parseFloat(root.dataset.clientBalance) || 0;
    this.orderType = root.dataset.orderType || 'contado';
    this.hasPendingCreditPayment = root.dataset.hasPendingCreditPayment === 'true';
    this.csrfToken = root.dataset.csrfToken;
    this.initialBreakdown = this.parseJSON(root.dataset.initialBreakdown) || null;
    this.initialOrderTotal = parseFloat(root.dataset.initialOrderTotal) || 0;
    this.initialDiscount = parseFloat(root.dataset.initialDiscount) || 0;
    this.initialSubtotal = parseFloat(root.dataset.initialSubtotal) || 0;
  }

  parseJSON(raw) {
    try {
      return raw ? JSON.parse(raw) : null;
    } catch (error) {
      console.error('Failed to parse JSON config', error);
      return null;
    }
  }
}

class AlertManager {
  show(type, title, message, timeout = 5000) {
    const alertDiv = document.createElement('div');
    alertDiv.className = `alert alert-${type} alert-dismissible fade show`;
    alertDiv.innerHTML = `
      <strong>${title}</strong> ${message}
      <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
    `;

    const container = document.querySelector('.container-fluid.mt-4');
    const firstChild = container?.firstElementChild;
    if (container) {
      container.insertBefore(alertDiv, firstChild || null);
    }

    if (timeout) {
      setTimeout(() => alertDiv.remove(), timeout);
    }
  }
}

class DiscountManager {
  constructor(getOrderTotalFn, onDiscountChange) {
    this.getOrderTotal = getOrderTotalFn;
    this.onDiscountChange = onDiscountChange;
    this.amountInput = document.getElementById('discount-amount');
    this.percentInput = document.getElementById('discount-percent');
    this.applyButton = document.getElementById('discount-apply-btn');
  }

  init() {
    this.bindAmountInputs();
    this.bindPercentInputs();
    this.bindApplyButton();
  }

  bindAmountInputs() {
    const handler = event => {
      const amount = this.parseAmount(event.target.value);
      const total = this.getOrderTotal();
      if (total > 0) {
        this.syncPercent(amount, total);
      }
      this.syncAmount(amount);
    };

    this.amountInput?.addEventListener('input', handler);
  }

  bindPercentInputs() {
    const handler = event => {
      const percent = this.parseAmount(event.target.value);
      const total = this.getOrderTotal();
      const amount = total > 0 ? this.amountFromPercent(total, percent) : 0;
      this.syncAmount(amount);
      this.syncPercent(amount, total);
    };

    this.percentInput?.addEventListener('input', handler);
  }

  bindApplyButton() {
    this.applyButton?.addEventListener('click', () => {
      this.triggerChange(this.getAmount());
    });
  }

  parseAmount(value) {
    return Math.max(0, parseFloat(value) || 0);
  }

  amountFromPercent(total, percent) {
    const clamped = Math.min(Math.max(percent, 0), 100);
    return (total * clamped) / 100;
  }

  syncAmount(amount) {
    if (this.amountInput && parseFloat(this.amountInput.value || '0') !== amount) {
      this.amountInput.value = amount.toFixed(2);
    }
  }

  syncPercent(amount, total) {
    if (!this.percentInput || total <= 0) return;
    const percent = (amount / total) * 100;
    const next = Math.min(Math.max(percent, 0), 100);
    if (parseFloat(this.percentInput.value || '0') !== next) {
      this.percentInput.value = next.toFixed(2);
    }
  }

  getAmount() {
    return this.parseAmount(this.amountInput?.value || '0');
  }

  triggerChange(amount) {
    if (typeof this.onDiscountChange === 'function') {
      this.onDiscountChange(amount);
    }
  }

  setAmount(amount) {
    const parsed = this.parseAmount(amount);
    if (this.amountInput) {
      this.amountInput.value = parsed.toFixed(2);
    }
    const total = this.getOrderTotal();
    this.syncPercent(parsed, total);
  }
}

class AffordabilityStatusManager {
  constructor(config) {
    this.config = config;
    this.statusElement = document.getElementById('affordability-status');
    this.paymentMethodSelects = document.querySelectorAll('#payment-method-select, #payment-method-select-mobile');
  }

  update(orderTotal) {
    if (!this.statusElement) return;

    const total = parseFloat(orderTotal.toString().replace(/[^\d.-]/g, '')) || 0;
    const { clientBalance } = this.config;

    if (total === 0) {
      this.statusElement.innerHTML = '';
      return;
    }

    if (total <= clientBalance) {
      this.statusElement.innerHTML = `
        <div class="badge bg-success">
          <i class="fas fa-check-circle me-1"></i>
          Puede pagar con saldo
        </div>
      `;
      this.enableBalanceOption(true);
    } else {
      const shortfall = total - clientBalance;
      this.statusElement.innerHTML = `
        <div class="badge bg-warning">
          <i class="fas fa-info-circle me-1"></i>
          Requiere otro método<br>
          <small>Falta cubrir: $${shortfall.toFixed(2)}</small>
        </div>
      `;
      this.disableBalanceOption();
    }
  }

  enableBalanceOption(isSufficient) {
    this.paymentMethodSelects.forEach(select => {
      const option = select.querySelector('option[value="balance"]');
      if (option) {
        option.disabled = false;
        option.textContent = isSufficient ? 'Saldo (Suficiente)' : 'Saldo';
      }
    });
  }

  disableBalanceOption() {
    this.paymentMethodSelects.forEach(select => {
      const option = select.querySelector('option[value="balance"]');
      if (option) {
        option.disabled = true;
        option.textContent = 'Saldo (Insuficiente)';
      }
    });
  }
}

class PaymentBreakdownManager {
  constructor(config) {
    this.config = config;
    this.currentBreakdown = {
      use_balance: false,
      balance_amount: '0.00',
      remaining_amount: '0.00',
      balance_covers_order: false,
      message: ''
    };
    this.balanceSection = document.getElementById('balance-payment-section');
    this.remainingSection = document.getElementById('remaining-payment-section');
    this.noBalanceSection = document.getElementById('no-balance-payment-section');
    this.summaryMessage = document.getElementById('payment-breakdown-message');
    this.paymentMethodCard = document.querySelector('#payment-method-select')?.closest('.card');
    this.balanceAmount = document.getElementById('balance-payment-amount');
    this.remainingAmount = document.getElementById('remaining-payment-amount');
    this.fullPaymentAmount = document.getElementById('full-payment-amount');
    this.secondaryPaymentMethod = document.getElementById('secondary-payment-method');
  }

  calculateFallbackBreakdown(orderTotal) {
    const total = parseFloat(orderTotal) || 0;
    const availableBalance = parseFloat(this.config.clientBalance) || 0;

    if (total <= 0) {
      return {
        use_balance: false,
        balance_amount: '0.00',
        remaining_amount: '0.00',
        balance_covers_order: false,
        message: ''
      };
    }

    if (availableBalance <= 0) {
      return {
        use_balance: false,
        balance_amount: '0.00',
        remaining_amount: total.toFixed(2),
        balance_covers_order: false,
        message: 'Sin saldo disponible. Pago completo con otro método.'
      };
    }

    if (availableBalance >= total) {
      return {
        use_balance: true,
        balance_amount: total.toFixed(2),
        remaining_amount: '0.00',
        balance_covers_order: true,
        message: `Pago completo con saldo disponible ($${total.toFixed(2)})`
      };
    }

    const remaining = total - availableBalance;
    return {
      use_balance: true,
      balance_amount: availableBalance.toFixed(2),
      remaining_amount: remaining.toFixed(2),
      balance_covers_order: false,
      message: `Saldo: $${availableBalance.toFixed(2)} + Otro método: $${remaining.toFixed(2)}`
    };
  }

  setBreakdown(breakdown) {
    this.currentBreakdown = breakdown || this.currentBreakdown;
  }

  getBreakdown() {
    return this.currentBreakdown;
  }

  updateUI(breakdown, orderTotal) {
    this.setBreakdown(breakdown);
    this.hideSections();

    const total = parseFloat(orderTotal) || 0;
    if (total === 0) {
      if (this.summaryMessage) {
        this.summaryMessage.innerHTML = '<i class="fas fa-info-circle me-1"></i>Agregue productos para ver el desglose de pago';
      }
      if (this.paymentMethodCard) this.paymentMethodCard.style.display = 'block';
      return;
    }

    if (breakdown.use_balance) {
      if (this.balanceSection) {
        this.balanceSection.style.display = 'block';
        if (this.balanceAmount) this.balanceAmount.textContent = '$' + parseFloat(breakdown.balance_amount).toFixed(2);
      }

      if (breakdown.balance_covers_order) {
        if (this.summaryMessage) {
          this.summaryMessage.innerHTML = `
            <i class="fas fa-check-circle text-success me-1"></i>
            <strong class="text-success">${breakdown.message}</strong>
          `;
        }
      } else {
        if (this.remainingSection) {
          this.remainingSection.style.display = 'block';
          if (this.remainingAmount) this.remainingAmount.textContent = '$' + parseFloat(breakdown.remaining_amount).toFixed(2);
        }
        if (this.summaryMessage) {
          this.summaryMessage.innerHTML = `
            <i class="fas fa-calculator text-warning me-1"></i>
            <strong class="text-warning">${breakdown.message}</strong>
          `;
        }
      }
    } else {
      if (this.noBalanceSection) {
        this.noBalanceSection.style.display = 'block';
        if (this.fullPaymentAmount) this.fullPaymentAmount.textContent = '$' + total.toFixed(2);
      }
      if (this.summaryMessage) {
        this.summaryMessage.innerHTML = `
          <i class="fas fa-info-circle text-secondary me-1"></i>
          <span class="text-muted">${breakdown.message}</span>
        `;
      }
      if (this.paymentMethodCard) this.paymentMethodCard.style.display = 'block';
    }
  }

  hideSections() {
    if (this.balanceSection) this.balanceSection.style.display = 'none';
    if (this.remainingSection) this.remainingSection.style.display = 'none';
    if (this.noBalanceSection) this.noBalanceSection.style.display = 'none';
    if (this.paymentMethodCard) this.paymentMethodCard.style.display = 'none';
  }
}

class OrderSummaryManager {
  update(productId, quantity, data) {
    this.updateList(document.getElementById('order-summary-products'), productId, quantity, data, false);
    this.updateList(document.getElementById('order-summary-products-mobile'), productId, quantity, data, true);

    const totalMobile = document.querySelector('.total-mobile');
    if (totalMobile && data.order_total) {
      totalMobile.textContent = data.order_total;
    }
  }

  updateList(listElement, productId, quantity, data, isMobile) {
    if (!listElement) return;

    const existingEmpty = listElement.querySelector('li:only-child');
    if (existingEmpty && existingEmpty.textContent.includes('No hay productos')) {
      existingEmpty.remove();
    }

    let existingItem = listElement.querySelector(`[data-product-id="${productId}"]`);

    if (parseInt(quantity, 10) > 0) {
      const productRow = document.querySelector(`[data-product="${productId}"]`)?.closest('tr');
      const productName = productRow?.dataset.productName?.trim() || '';
      const productPresentation = productRow?.dataset.productPresentation?.trim() || '';
      const unitPrice = parseFloat(productRow?.dataset.unitPrice || '0') || 0;
      const fullProductName = productPresentation ? `${productName} - ${productPresentation}` : productName;
      const itemTotal = (unitPrice * parseInt(quantity, 10)).toFixed(2);
      const orderId = document.querySelector('[data-order]')?.getAttribute('data-order');

      if (existingItem) {
        const productNameDiv = existingItem.querySelector('.fw-bold, .flex-grow-1 > div:first-child');
        const quantitySmall = existingItem.querySelector('small');
        const badge = existingItem.querySelector('.badge');
        if (productNameDiv) productNameDiv.textContent = fullProductName;
        if (quantitySmall) quantitySmall.textContent = `Cantidad: ${quantity}`;
        if (badge) badge.textContent = `$${itemTotal}`;
      } else {
        const newItem = document.createElement('li');
        newItem.setAttribute('data-product-id', productId);
        newItem.setAttribute('data-order-id', orderId || '');

        if (isMobile) {
          newItem.className = 'list-group-item d-flex justify-content-between align-items-center';
          newItem.innerHTML = `
            <div class="flex-grow-1">
              <div class="fw-bold">${fullProductName}</div>
              <small class="text-muted">Cantidad: ${quantity}</small>
            </div>
            <div class="d-flex align-items-center">
              <span class="badge bg-primary rounded-pill me-2">$${itemTotal}</span>
              <button type="button" class="btn btn-sm btn-outline-danger remove-item-btn-mobile" data-product-id="${productId}" data-order-id="${orderId}">
                <i class="fas fa-times"></i>
              </button>
            </div>
          `;
        } else {
          newItem.className = 'list-group-item d-flex justify-content-between align-items-center border-0 px-0';
          newItem.innerHTML = `
            <div class="flex-grow-1">
              <div class="fw-bold">${fullProductName}</div>
              <small class="text-muted">Cantidad: ${quantity}</small>
            </div>
            <div class="d-flex align-items-center">
              <span class="badge bg-primary rounded-pill me-2">$${itemTotal}</span>
              <button type="button" class="btn btn-sm btn-outline-danger remove-item-btn btn-touch" data-product-id="${productId}" data-order-id="${orderId}" title="Remover producto">
                <i class="fas fa-times"></i>
              </button>
            </div>
          `;
        }

        listElement.appendChild(newItem);
      }
    } else if (existingItem) {
      existingItem.remove();
      if (listElement.children.length === 0) {
        const emptyItem = document.createElement('li');
        emptyItem.className = isMobile ? 'list-group-item text-muted text-center py-4' : 'list-group-item border-0 px-0 text-muted text-center py-4';
        emptyItem.innerHTML = `
          <i class="fas fa-shopping-cart fa-2x mb-2 d-block"></i>
          No hay productos en el pedido
        `;
        listElement.appendChild(emptyItem);
      }
    }
  }
}

class AmountFieldManager {
  constructor() {
    this.cantidadCobradaInput = document.getElementById('cantidad_cobrada');
    this.cantidadCobradaMobileInput = document.getElementById('cantidad_cobrada_mobile');
    this.balanceAlert = document.getElementById('balance-addition-alert');
    this.balanceAlertMobile = document.getElementById('balance-addition-alert-mobile');
    this.balanceText = document.getElementById('balance-addition-text');
    this.balanceTextMobile = document.getElementById('balance-addition-text-mobile');
  }

  init(initialTotal) {
    this.bindValidation();
    if (initialTotal > 0) this.updateFields(initialTotal);
  }

  bindValidation() {
    if (this.cantidadCobradaInput && this.balanceAlert && this.balanceText) {
      this.cantidadCobradaInput.addEventListener('input', () => {
        this.cantidadCobradaInput.dataset.autoUpdated = 'false';
        this.validate(this.cantidadCobradaInput, this.balanceAlert, this.balanceText, false);
        this.syncValues(this.cantidadCobradaInput, this.cantidadCobradaMobileInput);
      });
      this.cantidadCobradaInput.addEventListener('blur', () => this.validate(this.cantidadCobradaInput, this.balanceAlert, this.balanceText, false));
    }

    if (this.cantidadCobradaMobileInput && this.balanceAlertMobile && this.balanceTextMobile) {
      this.cantidadCobradaMobileInput.addEventListener('input', () => {
        this.cantidadCobradaMobileInput.dataset.autoUpdated = 'false';
        this.validate(this.cantidadCobradaMobileInput, this.balanceAlertMobile, this.balanceTextMobile, true);
        this.syncValues(this.cantidadCobradaMobileInput, this.cantidadCobradaInput);
      });
      this.cantidadCobradaMobileInput.addEventListener('blur', () => this.validate(this.cantidadCobradaMobileInput, this.balanceAlertMobile, this.balanceTextMobile, true));
    }
  }

  updateFields(newTotal, force = false) {
    this.setFieldValue(this.cantidadCobradaInput, newTotal, force);
    this.setFieldValue(this.cantidadCobradaMobileInput, newTotal, force);
    this.revalidate(newTotal);
  }

  setFieldValue(input, value, force = false) {
    if (!input) return;
    if (force) {
      input.value = value.toFixed(2);
      input.dataset.autoUpdated = 'true';
      return;
    }

    const currentValue = parseFloat(input.value) || 0;
    if (currentValue === 0 || input.dataset.autoUpdated === 'true') {
      input.value = value.toFixed(2);
      input.dataset.autoUpdated = 'true';
    }
  }

  revalidate(orderTotal) {
    if (this.cantidadCobradaInput && this.balanceAlert && this.balanceText) {
      this.validate(this.cantidadCobradaInput, this.balanceAlert, this.balanceText, false, orderTotal);
    }
    if (this.cantidadCobradaMobileInput && this.balanceAlertMobile && this.balanceTextMobile) {
      this.validate(this.cantidadCobradaMobileInput, this.balanceAlertMobile, this.balanceTextMobile, true, orderTotal);
    }
  }

  getCurrentOrderTotal() {
    const totalElement = document.querySelector('.badge.bg-success.fs-4, .total-mobile');
    if (!totalElement) return 0;
    const totalText = totalElement.textContent || totalElement.innerText;
    return parseFloat(totalText.replace(/[^\d.-]/g, '')) || 0;
  }

  validate(input, alertElement, textElement, isMobile = false, overrideTotal) {
    if (!input || !alertElement || !textElement) return;

    const cantidadCobrada = parseFloat(input.value) || 0;
    const orderTotal = overrideTotal !== undefined ? overrideTotal : this.getCurrentOrderTotal();
    const otherInput = isMobile ? document.getElementById('cantidad_cobrada') : document.getElementById('cantidad_cobrada_mobile');
    const otherAlert = isMobile ? document.getElementById('balance-addition-alert') : document.getElementById('balance-addition-alert-mobile');
    const otherText = isMobile ? document.getElementById('balance-addition-text') : document.getElementById('balance-addition-text-mobile');

    if (otherInput) otherInput.value = input.value;

    if (cantidadCobrada < orderTotal) {
      input.setCustomValidity('La cantidad cobrada no puede ser menor al total de la orden');
      input.classList.add('is-invalid');
      alertElement.style.display = 'none';
      if (otherAlert) otherAlert.style.display = 'none';
    } else if (cantidadCobrada > orderTotal) {
      const excess = cantidadCobrada - orderTotal;
      input.setCustomValidity('');
      input.classList.remove('is-invalid');
      input.classList.add('is-valid');
      alertElement.style.display = 'block';
      alertElement.className = isMobile ? 'alert alert-info alert-sm mt-1 p-2' : 'alert alert-info mt-2';
      textElement.innerHTML = `Vas a agregar <strong>$${excess.toFixed(2)}</strong> al saldo del cliente`;
      if (otherAlert && otherText) {
        otherAlert.style.display = 'block';
        otherAlert.className = isMobile ? 'alert alert-info mt-2' : 'alert alert-info alert-sm mt-1 p-2';
        otherText.innerHTML = `Vas a agregar <strong>$${excess.toFixed(2)}</strong> al saldo del cliente`;
      }
    } else {
      input.setCustomValidity('');
      input.classList.remove('is-invalid', 'is-valid');
      alertElement.style.display = 'none';
      if (otherAlert) otherAlert.style.display = 'none';
    }

    document.dispatchEvent(new CustomEvent('amount-validation-changed'));
  }

  syncValues(source, target) {
    if (target) {
      target.value = source.value;
      target.dataset.autoUpdated = source.dataset.autoUpdated || 'false';
    }
  }
}

class OrderApi {
  constructor(config) {
    this.config = config;
  }

  async updateOrder(payload) {
    const response = await fetch(`/orders/${this.config.orderId}/update/`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': this.config.csrfToken
      },
      body: JSON.stringify(payload)
    });
    return response.json();
  }

  async updateQuantity(productId, quantity) {
    const response = await fetch(`/orders/${this.config.orderId}/update/`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': this.config.csrfToken
      },
      body: JSON.stringify({ quantity, product_id: productId })
    });
    return response.json();
  }

  async submitPayment(payload) {
    const response = await fetch('/payments/create/', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': this.config.csrfToken
      },
      body: JSON.stringify(payload)
    });
    return response.json();
  }

  async cancelOrder() {
    const response = await fetch(this.config.cancelOrderUrl, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': this.config.csrfToken
      },
      body: JSON.stringify({})
    });
    return response.json();
  }
}

class OrderNotesController {
  constructor(api, alertManager) {
    this.api = api;
    this.alertManager = alertManager;
    this.desktopInput = document.getElementById('order-notes-desktop');
    this.mobileInput = document.getElementById('order-notes-mobile');
    this.hiddenInput = document.getElementById('id_notes');
    this.desktopStatus = document.getElementById('order-notes-status');
    this.mobileStatus = document.getElementById('order-notes-status-mobile');
    this.saveTimer = null;
    this.lastSavedValue = this.getCurrentValue();
  }

  init() {
    this.syncAll(this.lastSavedValue);
    this.bindInput(this.desktopInput, this.mobileInput);
    this.bindInput(this.mobileInput, this.desktopInput);
  }

  bindInput(source, target) {
    if (!source) {
      return;
    }

    source.addEventListener('input', () => {
      const value = source.value;
      if (target && target.value !== value) {
        target.value = value;
      }
      this.syncHidden(value);
      this.setStatus('Guardando...');
      window.clearTimeout(this.saveTimer);
      this.saveTimer = window.setTimeout(() => this.persist(value), 500);
    });

    source.addEventListener('blur', () => {
      const value = source.value;
      this.syncHidden(value);
      this.persist(value);
    });
  }

  syncAll(value) {
    if (this.desktopInput) this.desktopInput.value = value;
    if (this.mobileInput) this.mobileInput.value = value;
    this.syncHidden(value);
  }

  syncHidden(value) {
    if (this.hiddenInput) {
      this.hiddenInput.value = value;
    }
  }

  getCurrentValue() {
    return this.desktopInput?.value || this.mobileInput?.value || this.hiddenInput?.value || '';
  }

  getValue() {
    return this.getCurrentValue().trim();
  }

  setStatus(message) {
    if (this.desktopStatus) this.desktopStatus.textContent = message;
    if (this.mobileStatus) this.mobileStatus.textContent = message;
  }

  async persist(value) {
    const normalized = value.trim();
    if (normalized === this.lastSavedValue.trim()) {
      this.setStatus(normalized ? 'Guardado' : 'Sin nota');
      return;
    }

    try {
      const data = await this.api.updateOrder({ notes: value });
      this.lastSavedValue = data.notes || '';
      this.syncAll(this.lastSavedValue);
      this.setStatus(this.lastSavedValue ? 'Guardado' : 'Sin nota');
    } catch (error) {
      this.setStatus('Error al guardar');
      this.alertManager.show('danger', 'Error', 'No se pudo guardar la nota del pedido.', 4000);
      console.error('Order notes save error', error);
    }
  }
}

class NavigationController {
  constructor(api, alertManager) {
    this.api = api;
    this.alertManager = alertManager;
    this.cancelButton = document.getElementById('cancel-order-btn');
    this.fallbackRedirectUrl = '/clients/';
  }

  init() {
    this.cancelButton?.addEventListener('click', event => this.handleCancel(event));
  }

  async handleCancel(event) {
    event.preventDefault();

    const confirmed = window.confirm('¿Desea cancelar este pedido? Se eliminarán el pedido y sus productos asociados.');
    if (!confirmed) {
      return;
    }

    try {
      const data = await this.api.cancelOrder();
      if (!data.success) {
        throw new Error(data.error || 'No se pudo cancelar el pedido.');
      }

      this.alertManager.show('success', 'Pedido cancelado', data.message || 'Pedido cancelado correctamente.', 2000);
      window.location.href = data.redirect_url || this.fallbackRedirectUrl;
    } catch (error) {
      this.alertManager.show('danger', 'Error', error.message || 'No se pudo cancelar el pedido.', 5000);
      console.error('Cancel order error', error);
    }
  }
}

class QuantityController {
  constructor(config, api, alertManager, summaryManager, paymentBreakdown, affordabilityManager, amountManager, discountManager, applyTotals) {
    this.config = config;
    this.api = api;
    this.alertManager = alertManager;
    this.summaryManager = summaryManager;
    this.paymentBreakdown = paymentBreakdown;
    this.affordabilityManager = affordabilityManager;
    this.amountManager = amountManager;
    this.discountManager = discountManager;
    this.applyTotals = applyTotals;
  }

  init() {
    this.bindAddRemove();
    this.bindSummaryRemoval();
  }

  bindAddRemove() {
    const addButtons = document.querySelectorAll('button.btn-success[data-product]');
    const removeButtons = document.querySelectorAll('button.btn-danger[data-product]');

    addButtons.forEach(button => {
      button.addEventListener('click', () => this.handleQuantityChange(button, 0, true));
    });

    removeButtons.forEach(button => {
      button.addEventListener('click', () => this.handleQuantityChange(button, -1));
    });
  }

  bindSummaryRemoval() {
    document.addEventListener('click', event => {
      const button = event.target.closest('.remove-item-btn, .remove-item-btn-mobile');
      if (!button) return;
      const productId = button.getAttribute('data-product-id');
      this.confirmAndRemove(productId);
    });
  }

  async handleQuantityChange(button, delta, useInputValue = false) {
    const row = button.closest('tr');
    const qtyInput = row?.querySelector('input[type="number"]');
    const productId = button.getAttribute('data-product');
    if (!qtyInput || !productId) return;

    const currentValue = parseInt(qtyInput.value || '0', 10) || 0;
    const newValue = useInputValue
      ? Math.max(currentValue || 1, 0)
      : Math.max(0, currentValue + delta);
    qtyInput.value = newValue;

    try {
      const data = await this.api.updateOrder({ quantity: newValue, product_id: productId, discount: this.discountManager.getAmount() });
      this.afterQuantityUpdate(productId, newValue, data);
    } catch (error) {
      this.alertManager.show('danger', 'Error', 'No se pudo actualizar el pedido.', 5000);
      console.error('Update quantity error', error);
    }
  }

  async confirmAndRemove(productId) {
    if (!window.confirm('¿Está seguro de que desea remover este producto del pedido?')) return;
    try {
      const data = await this.api.updateOrder({ quantity: 0, product_id: productId, discount: this.discountManager.getAmount() });
      const qtyInput = document.querySelector(`input[name="qty_${productId}"]`);
      if (qtyInput) qtyInput.value = 0;
      this.afterQuantityUpdate(productId, 0, data);
    } catch (error) {
      this.alertManager.show('danger', 'Error', 'No se pudo remover el producto.', 5000);
      console.error('Remove product error', error);
    }
  }

  afterQuantityUpdate(productId, quantity, data) {
    if (typeof this.applyTotals === 'function') {
      this.applyTotals(data);
    } else {
      if (data.order_total) {
        const totalElement = document.querySelector('.badge.bg-success.fs-4');
        const totalMobile = document.querySelector('.total-mobile');
        if (totalElement) totalElement.textContent = data.order_total;
        if (totalMobile) totalMobile.textContent = data.order_total;
        this.affordabilityManager.update(data.order_total);
        const numericTotal = parseFloat(data.order_total.replace(/[^\d.-]/g, '')) || 0;
        this.amountManager.updateFields(numericTotal);
      }
      if (data.payment_breakdown) {
        this.paymentBreakdown.updateUI(data.payment_breakdown, data.order_total);
      }
    }

    this.summaryManager.update(productId, quantity, data);
    this.alertManager.show('success', 'Éxito', 'Pedido actualizado correctamente.', 3000);
  }
}

class PaymentController {
  constructor(config, api, alertManager, paymentBreakdown, amountManager, discountManager, orderNotesController) {
    this.config = config;
    this.api = api;
    this.alertManager = alertManager;
    this.paymentBreakdown = paymentBreakdown;
    this.amountManager = amountManager;
    this.discountManager = discountManager;
    this.orderNotesController = orderNotesController;
    this.finishButton = document.getElementById('finish-order-btn');
    this.finishButtonMobile = document.getElementById('finish-order-btn-mobile');
  }

  init() {
    this.bindOrderTypeSync();
    this.configureOrderTypeUI();
    this.finishButton?.addEventListener('click', () => this.handleFinish());
    this.finishButtonMobile?.addEventListener('click', () => this.handleFinish());

    //document.addEventListener('amount-validation-changed', () => this.validateFinishButtonState());
    //this.validateFinishButtonState();
  }

  validateFinishButtonState() {
    const orderType = this.getOrderType();
    let isValid = false;

    if (orderType === 'credito') {
      isValid = true;
    } else {
      const cantidadCobrada = this.getCantidadCobrada() || 0;
      const orderTotal = this.getOrderTotal();
      if (cantidadCobrada >= orderTotal - 0.01) {
        isValid = true;
      }
    }

    if (this.finishButton && !this.finishButton.innerHTML.includes('spinner-border')) {
      this.finishButton.disabled = !isValid;
    }
    if (this.finishButtonMobile && !this.finishButtonMobile.innerHTML.includes('spinner-border')) {
      this.finishButtonMobile.disabled = !isValid;
    }
  }

  bindOrderTypeSync() {
    const desktop = document.getElementById('order-type-select');
    const mobile = document.getElementById('order-type-select-mobile');

    desktop?.addEventListener('change', () => {
      if (mobile) mobile.value = desktop.value;
      this.config.orderType = desktop.value;
      this.configureOrderTypeUI();
    });

    mobile?.addEventListener('change', () => {
      if (desktop) desktop.value = mobile.value;
      this.config.orderType = mobile.value;
      this.configureOrderTypeUI();
    });
  }

  configureOrderTypeUI() {
    const orderType = this.getOrderType();
    const paymentMethodDesktop = document.getElementById('payment-method-select');
    const paymentMethodMobile = document.getElementById('payment-method-select-mobile');
    const orderTypeDesktop = document.getElementById('order-type-select');
    const orderTypeMobile = document.getElementById('order-type-select-mobile');
    const cantidadCobradaDesktop = document.getElementById('cantidad_cobrada');
    const cantidadCobradaMobile = document.getElementById('cantidad_cobrada_mobile');
    const paymentBreakdownCard = document.getElementById('payment-breakdown-card');
    const helpText = document.getElementById('order-type-help-text');

    const isCredit = orderType === 'credito';
    const isCreditRegistration = isCredit && !this.config.hasPendingCreditPayment;
    const isCreditSettlement = isCredit && this.config.hasPendingCreditPayment;

    this.syncPaymentMethodSelectionForCredit(isCredit);

    // Hide/show payment method containers
    if (paymentMethodDesktop) {
      const container = paymentMethodDesktop.closest('.mb-3');
      if (container) container.style.display = isCredit ? 'none' : 'block';
    }
    if (paymentMethodMobile) {
      const container = paymentMethodMobile.closest('.mb-3');
      if (container) container.style.display = isCredit ? 'none' : 'block';
    }

    // Hide/show cantidad cobrada containers
    if (cantidadCobradaDesktop) {
      const container = cantidadCobradaDesktop.closest('.mb-3');
      if (container) container.style.display = isCredit ? 'none' : 'block';
    }
    if (cantidadCobradaMobile) {
      const container = cantidadCobradaMobile.closest('.mb-3');
      if (container) container.style.display = isCredit ? 'none' : 'block';
    }

    if (paymentBreakdownCard) paymentBreakdownCard.style.display = isCredit ? 'none' : 'block';

    if (helpText) {
      helpText.textContent = isCreditRegistration
        ? 'Al terminar, se registrará deuda y la orden quedará pendiente hasta liquidarse.'
        : 'Las órdenes a crédito registran deuda y quedan pendientes hasta liquidarse.';
    }

    if (this.finishButton) {
      this.finishButton.innerHTML = isCreditRegistration
        ? '<i class="fas fa-hourglass-half me-2"></i>Registrar Como Pendiente'
        : '<i class="fas fa-check-circle me-2"></i>Terminar Pedido';
    }

    if (this.finishButtonMobile) {
      this.finishButtonMobile.innerHTML = isCreditRegistration
        ? '<i class="fas fa-hourglass-half me-2"></i>Pendiente'
        : '<i class="fas fa-check-circle me-2"></i>Terminar';
    }

    //this.validateFinishButtonState();
  }

  syncPaymentMethodSelectionForCredit(isCredit) {
    const selectIds = ['payment-method-select', 'payment-method-select-mobile'];

    selectIds.forEach(selectId => {
      const select = document.getElementById(selectId);
      if (!select) return;

      const placeholderValue = '__credit_no_payment__';
      let placeholderOption = select.querySelector(`option[value="${placeholderValue}"]`);

      if (isCredit) {
        if (!placeholderOption) {
          placeholderOption = document.createElement('option');
          placeholderOption.value = placeholderValue;
          placeholderOption.textContent = 'Sin metodo de pago (credito)';
          select.prepend(placeholderOption);
        }
        select.value = placeholderValue;
      } else if (placeholderOption) {
        const wasSelected = select.value === placeholderValue;
        placeholderOption.remove();
        if (wasSelected && select.options.length > 0) {
          select.selectedIndex = 0;
        }
      }
    });
  }

  getOrderTotal() {
    const totalElement = document.querySelector('.badge.bg-success.fs-4, .total-mobile');
    const orderTotalStr = totalElement ? totalElement.textContent : '0.00';
    return parseFloat(orderTotalStr.replace(/[^\d.-]/g, '')) || 0;
  }

  getPaymentMethod() {
    const paymentMethodSelect = document.getElementById('payment-method-select');
    const paymentMethodSelectMobile = document.getElementById('payment-method-select-mobile');
    if (paymentMethodSelect?.value) return paymentMethodSelect.value;
    if (paymentMethodSelectMobile?.value) return paymentMethodSelectMobile.value;
    return '';
  }

  getOrderType() {
    const desktop = document.getElementById('order-type-select');
    const mobile = document.getElementById('order-type-select-mobile');
    if (desktop?.value) return desktop.value;
    if (mobile?.value) return mobile.value;
    return this.config.orderType || 'contado';
  }

  buildPayments(orderTotal) {
    const payments = [];
    const breakdown = this.paymentBreakdown.getBreakdown();

    if (breakdown.use_balance) {
      const balanceAmount = parseFloat(breakdown.balance_amount) || 0;
      if (balanceAmount > 0) {
        payments.push({ amount: balanceAmount, payment_method: 'balance' });
      }

      const remainingAmount = parseFloat(breakdown.remaining_amount) || 0;
      if (remainingAmount > 0) {
        const secondaryPaymentSelect = document.getElementById('secondary-payment-method');
        const method = secondaryPaymentSelect?.value || 'cash';
          payments.push({ amount: remainingAmount, payment_method: method });
      }
    } else {
      const method = this.getPaymentMethod();
      if (!method) {
        this.alertManager.show('warning', 'Atención', 'Seleccione un método de pago.');
        return null;
      }

      payments.push({ amount: orderTotal, payment_method: method });
    }

    return payments;
  }

  disableButtons() {
    if (this.finishButton) {
      this.finishButton.disabled = true;
      this.finishButton.innerHTML = '<span class="spinner-border spinner-border-sm me-2" role="status"></span>Procesando...';
    }
    if (this.finishButtonMobile) {
      this.finishButtonMobile.disabled = true;
      this.finishButtonMobile.innerHTML = '<span class="spinner-border spinner-border-sm me-2" role="status"></span>Procesando...';
    }
  }

  enableButtons() {
    if (this.finishButton) {
      this.finishButton.disabled = false;
      this.finishButton.innerHTML = '<i class="fas fa-check-circle me-2"></i>Terminar Pedido';
    }
    if (this.finishButtonMobile) {
      this.finishButtonMobile.disabled = false;
      this.finishButtonMobile.innerHTML = '<i class="fas fa-check-circle me-2"></i>Terminar';
    }
    this.validateFinishButtonState();
  }

  async handleFinish() {
    const orderTotal = this.getOrderTotal();
    if (orderTotal === 0) {
      this.alertManager.show('warning', 'Atención', 'El pedido está vacío. Agregue productos antes de terminar.');
      return;
    }

    const orderType = this.getOrderType();

    if (orderType === 'credito') {
      const payload = {
        order_id: this.config.orderId,
        order_type: 'credito',
        notes: this.orderNotesController?.getValue() || ''
      };

      try {
        this.disableButtons();
        const data = await this.api.submitPayment(payload);
        if (data.success) {
          this.handleCreditOrderPendingSuccess(data);
        } else {
          throw new Error(data.error || 'Error al registrar orden a crédito');
        }
      } catch (error) {
        this.enableButtons();
        this.alertManager.show('danger', 'Error', `No se pudo registrar la orden a crédito. ${error.message}`);
        console.error('Credit order registration error', error);
      }
      return;
    }

    const payments = this.buildPayments(orderTotal);
    if (!payments) return;

    const cantidadCobrada = this.getCantidadCobrada();
    const payload = {
      order_id: this.config.orderId,
      order_type: orderType,
      payments,
      notes: this.orderNotesController?.getValue() || ''
    };
    if (cantidadCobrada !== null && cantidadCobrada > 0) payload.cantidad_cobrada = cantidadCobrada;

    try {
      this.disableButtons();
      const data = await this.api.submitPayment(payload);
      if (data.success) {
        this.handleSuccess(data);
      } else {
        throw new Error(data.error || 'Error al procesar el pago');
      }
    } catch (error) {
      this.enableButtons();
      this.alertManager.show('danger', 'Error', `No se pudo procesar el pago. ${error.message}`);
      console.error('Payment error', error);
    }
  }

  getCantidadCobrada() {
    const desktop = document.getElementById('cantidad_cobrada');
    const mobile = document.getElementById('cantidad_cobrada_mobile');
    if (desktop?.value) return parseFloat(desktop.value);
    if (mobile?.value) return parseFloat(mobile.value);
    return null;
  }

  handleSuccess(data) {
    let message = 'El pedido se ha completado correctamente.';

    if (data.payments?.length) {
      message += '<br><div class="mt-2 p-2 bg-light border rounded">';
      message += '<strong><i class="fas fa-receipt me-1"></i>Pagos registrados:</strong><ul class="mb-0 mt-1">';
      data.payments.forEach(p => {
        message += `<li>${p.method}: $${p.amount}</li>`;
      });
      message += '</ul></div>';
    } else if (data.method && data.amount) {
      message += `<br><small>Método de pago: ${data.method} - Monto: $${data.amount}</small>`;
    }

    if (data.balance_added && data.cantidad_cobrada) {
      message += '<br><div class="mt-2 p-2 bg-info bg-opacity-10 border border-info rounded">';
      message += '<i class="fas fa-plus-circle text-success me-1"></i>';
      message += `<strong>Saldo agregado:</strong> $${data.balance_added}<br>`;
      message += `<small>Cantidad cobrada: $${data.cantidad_cobrada} | Total orden: $${data.order_total}</small><br>`;
      message += `<small>Nuevo saldo del cliente: $${data.new_client_balance}</small>`;
      message += '</div>';
    }

    this.alertManager.show('success', 'Éxito', message, 8000);
    this.markCompleted();
    setTimeout(() => {
      window.location.href = document.getElementById('finish-order-btn')?.dataset.redirect || '/clients/';
    }, 3000);
  }

  handleCreditOrderPendingSuccess(data) {
    const message = data.message || 'Orden a crédito registrada y pendiente de pago.';
    this.alertManager.show('success', 'Orden a crédito', message, 6000);
    setTimeout(() => {
      window.location.href = document.getElementById('finish-order-btn')?.dataset.redirect || '/clients/';
    }, 2000);
  }

  markCompleted() {
    if (this.finishButton) {
      this.finishButton.innerHTML = '✓ Pedido Completado';
      this.finishButton.classList.remove('btn-success');
      this.finishButton.classList.add('btn-secondary');
    }
    if (this.finishButtonMobile) {
      this.finishButtonMobile.innerHTML = '✓ Completado';
      this.finishButtonMobile.classList.remove('btn-success');
      this.finishButtonMobile.classList.add('btn-secondary');
    }
    document.querySelectorAll('button:not(.btn-close), select, input').forEach(element => {
      if (!element.classList.contains('btn-close')) element.disabled = true;
    });
  }
}

class OrderPageApp {
  constructor(root) {
    this.root = root;
    this.config = new PageConfig(root);
    this.alertManager = new AlertManager();
    this.affordabilityStatusManager = new AffordabilityStatusManager(this.config);
    this.paymentBreakdownManager = new PaymentBreakdownManager(this.config);
    this.summaryManager = new OrderSummaryManager();
    this.amountFieldManager = new AmountFieldManager();
    this.api = new OrderApi(this.config);
    this.orderNotesController = new OrderNotesController(this.api, this.alertManager);
    this.navigationController = new NavigationController(this.api, this.alertManager);
    this.discountManager = new DiscountManager(() => this.getCurrentOrderTotal(), amount => this.handleDiscountChange(amount));
    this.quantityController = new QuantityController(
      this.config,
      this.api,
      this.alertManager,
      this.summaryManager,
      this.paymentBreakdownManager,
      this.affordabilityStatusManager,
      this.amountFieldManager,
      this.discountManager,
      data => this.applyServerTotals(data)
    );
    this.paymentController = new PaymentController(
      this.config,
      this.api,
      this.alertManager,
      this.paymentBreakdownManager,
      this.amountFieldManager,
      this.discountManager,
      this.orderNotesController
    );
  }

  init() {
    this.navigationController.init();
    this.orderNotesController.init();
    this.discountManager.init();
    if (this.config.initialDiscount) {
      this.discountManager.setAmount(this.config.initialDiscount);
    }
    this.quantityController.init();
    this.paymentController.init();
    const startingTotal = this.config.initialOrderTotal || this.getCurrentOrderTotal();
    this.amountFieldManager.init(startingTotal);
    this.affordabilityStatusManager.update(startingTotal);
    this.updateSummaryTotals(startingTotal, this.config.initialDiscount, this.config.initialSubtotal);

    const hasBalance = (parseFloat(this.config.clientBalance) || 0) > 0;
    const serverBreakdown = this.config.initialBreakdown;
    const shouldForceBalanceBreakdown = hasBalance && startingTotal > 0 && (!serverBreakdown || !serverBreakdown.use_balance);
    const initialBreakdown = shouldForceBalanceBreakdown
      ? this.paymentBreakdownManager.calculateFallbackBreakdown(startingTotal)
      : (serverBreakdown || this.paymentBreakdownManager.calculateFallbackBreakdown(startingTotal));

    this.paymentBreakdownManager.updateUI(initialBreakdown, startingTotal);
  }

  async handleDiscountChange(amount) {
    try {
      const data = await this.api.updateOrder({ discount: amount });
      this.applyServerTotals(data);
      this.alertManager.show('success', 'Descuento', 'Descuento aplicado. Recargando...', 1500);
      setTimeout(() => window.location.reload(), 1200);
    } catch (error) {
      this.alertManager.show('danger', 'Error', 'No se pudo aplicar el descuento.', 4000);
      console.error('Discount update error', error);
    }
  }

  applyServerTotals(data) {
    if (!data) return;
    if (data.order_total) {
      const totalElement = document.querySelector('.badge.bg-success.fs-4');
      const totalMobile = document.querySelector('.total-mobile');
      if (totalElement) totalElement.textContent = data.order_total;
      if (totalMobile) totalMobile.textContent = data.order_total;
      this.affordabilityStatusManager.update(data.order_total);
      const numericTotal = parseFloat(data.order_total.replace(/[^\d.-]/g, '')) || 0;
      this.amountFieldManager.updateFields(numericTotal, true);
      const discountAmount = data.discount ? parseFloat(data.discount) : this.discountManager.getAmount();
      const subtotal = data.subtotal ? parseFloat(data.subtotal) : undefined;
      if (data.discount) this.discountManager.setAmount(discountAmount);
      this.updateSummaryTotals(numericTotal, discountAmount, subtotal);
    }
    if (data.payment_breakdown) {
      this.paymentBreakdownManager.updateUI(data.payment_breakdown, data.order_total);
    }
  }

  updateSummaryTotals(orderTotalNumber, discountAmountOverride, subtotalOverride) {
    const discountAmount = typeof discountAmountOverride === 'number' ? discountAmountOverride : this.discountManager.getAmount();
    const subtotal = typeof subtotalOverride === 'number' ? subtotalOverride : orderTotalNumber + discountAmount;
    const format = value => `$${value.toFixed(2)}`;

    const subtotalEl = document.getElementById('summary-subtotal');
    const discountEl = document.getElementById('summary-discount');
    const discountMobileEl = document.getElementById('summary-discount-mobile');
    const totalEl = document.getElementById('summary-total');

    if (subtotalEl) subtotalEl.textContent = format(subtotal);
    if (discountEl) discountEl.textContent = format(discountAmount);
    if (discountMobileEl) discountMobileEl.textContent = format(discountAmount);
    if (totalEl) totalEl.textContent = orderTotalNumber.toFixed(2);
  }

  getCurrentOrderTotal() {
    const totalElement = document.querySelector('.badge.bg-success.fs-4, .total-mobile');
    if (!totalElement) return 0;
    const totalText = totalElement.textContent || totalElement.innerText;
    return parseFloat(totalText.replace(/[^\d.-]/g, '')) || 0;
  }
}

window.addEventListener('DOMContentLoaded', () => {
  const root = document.getElementById('order-page');
  if (!root) return;
  const app = new OrderPageApp(root);
  app.init();
});
