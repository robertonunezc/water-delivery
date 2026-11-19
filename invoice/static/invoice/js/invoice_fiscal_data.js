class InvoiceFiscalDataManager {
  constructor(form) {
    this.form = form;
    this.clientSelect = form.elements.namedItem('client');
    this.fields = Object.fromEntries(
      ['rfc', 'razon_social', 'curp', 'billing_address'].map(
        (name) => [name, form.elements.namedItem(name)],
      ),
    );
    this.status = document.getElementById('invoice-fiscal-data-status');
    this.submitButtons = Array.from(form.elements).filter((element) => element.type === 'submit');
    this.requestId = 0;
    this.loading = false;
    if (this.clientSelect) {
      if (typeof django !== 'undefined' && django.jQuery) {
        django.jQuery(this.clientSelect).on('change', () => this.load());
      } else {
        this.clientSelect.addEventListener('change', () => this.load());
      }
      form.addEventListener('submit', (event) => {
        if (this.loading) event.preventDefault();
      });
    }
  }

  setLoading(loading) {
    this.loading = loading;
    Object.values(this.fields).forEach((field) => { field.disabled = loading; });
    this.submitButtons.forEach((button) => { button.disabled = loading; });
  }

  async load() {
    const requestId = ++this.requestId;
    const clientId = this.clientSelect.value;
    Object.values(this.fields).forEach((field) => { field.value = ''; });
    this.status.textContent = clientId ? 'Cargando datos fiscales...' : '';
    this.setLoading(Boolean(clientId));
    if (!clientId) return;

    try {
      const url = this.form.dataset.fiscalDataUrl.replace('/0/', `/${clientId}/`);
      const response = await fetch(url);
      if (!response.ok) throw new Error('Fiscal data unavailable');
      const data = await response.json();
      if (requestId !== this.requestId) return;
      Object.entries(this.fields).forEach(([name, field]) => {
        field.value = data.fiscal_data[name] || '';
      });
      this.status.textContent = 'Datos fiscales del cliente cargados.';
    } catch (error) {
      if (requestId !== this.requestId) return;
      this.status.textContent = 'No fue posible cargar los datos fiscales. Puedes ingresarlos manualmente.';
    } finally {
      if (requestId === this.requestId) this.setLoading(false);
    }
  }
}

document.addEventListener('DOMContentLoaded', () => {
  const form = document.getElementById('invoice-create-form') || document.getElementById('invoice_form');
  const config = document.getElementById('invoice-fiscal-data-config');
  if (form && config) form.dataset.fiscalDataUrl = config.dataset.url;
  if (form && form.dataset.fiscalDataUrl && form.elements.namedItem('client')) {
    new InvoiceFiscalDataManager(form);
  }
});
