document.addEventListener('DOMContentLoaded', () => {
  const form = document.getElementById('credit-report-payment-form');
  if (!form) return;
  const orders = Array.from(document.querySelectorAll('.credit-report-order-checkbox'));
  const invoices = Array.from(document.querySelectorAll('.credit-report-invoice-checkbox'));
  const selectAll = document.getElementById('select-all-credit-orders');
  const payButton = document.getElementById('pay-credit-report-orders');
  const summary = document.getElementById('credit-report-selected-total');

  function updateSelection() {
    const selected = orders.filter((order) => order.checked);
    const cents = selected.reduce((total, order) => (
      total + Math.round(Number.parseFloat(order.dataset.amount) * 100)
    ), 0);
    const label = selected.length === 1 ? 'pedido seleccionado' : 'pedidos seleccionados';
    summary.textContent = `${selected.length} ${label} · $${(cents / 100).toFixed(2)}`;
    payButton.disabled = selected.length === 0;
    selectAll.checked = orders.length > 0 && selected.length === orders.length;
    selectAll.indeterminate = selected.length > 0 && selected.length < orders.length;
    invoices.forEach((invoice) => {
      const group = orders.filter((order) => order.dataset.invoice === invoice.dataset.invoice);
      const count = group.filter((order) => order.checked).length;
      invoice.checked = group.length > 0 && count === group.length;
      invoice.indeterminate = count > 0 && count < group.length;
    });
  }

  orders.forEach((order) => order.addEventListener('change', updateSelection));
  invoices.forEach((invoice) => invoice.addEventListener('change', () => {
    orders.filter((order) => order.dataset.invoice === invoice.dataset.invoice)
      .forEach((order) => { order.checked = invoice.checked; });
    updateSelection();
  }));
  selectAll.addEventListener('change', () => {
    orders.forEach((order) => { order.checked = selectAll.checked; });
    updateSelection();
  });
  form.addEventListener('submit', (event) => {
    if (!orders.some((order) => order.checked)) event.preventDefault();
  });
  updateSelection();
});
