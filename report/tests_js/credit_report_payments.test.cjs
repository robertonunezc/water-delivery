const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(
  path.join(__dirname, '../static/report/js/credit_report_payments.js'), 'utf8',
);

function element(dataset = {}) {
  return {
    dataset, checked: false, disabled: false, indeterminate: false, textContent: '', listeners: {},
    addEventListener(name, callback) { this.listeners[name] = callback; },
  };
}

function setup() {
  const orders = [
    element({ invoice: '42', amount: '100.25' }),
    element({ invoice: '42', amount: '24.75' }),
    element({ amount: '35.00' }),
  ];
  const invoice = element({ invoice: '42' });
  const form = element();
  const selectAll = element();
  const button = element();
  const summary = element();
  const elements = {
    'credit-report-payment-form': form,
    'select-all-credit-orders': selectAll,
    'pay-credit-report-orders': button,
    'credit-report-selected-total': summary,
  };
  const document = {
    getElementById: (id) => elements[id],
    querySelectorAll: (selector) => selector === '.credit-report-order-checkbox' ? orders : [invoice],
    addEventListener: (_name, callback) => callback(),
  };
  vm.runInNewContext(source, { document });
  return { orders, invoice, form, selectAll, button, summary };
}

test('no selection disables payment and prevents empty submission', () => {
  const ui = setup();
  assert.equal(ui.button.disabled, true);
  assert.equal(ui.summary.textContent, '0 pedidos seleccionados · $0.00');
  const event = { prevented: false, preventDefault() { this.prevented = true; } };
  ui.form.listeners.submit(event);
  assert.equal(event.prevented, true);
});

test('selecting an invoice checks only its orders and totals their open amounts', () => {
  const ui = setup();
  ui.invoice.checked = true;
  ui.invoice.listeners.change();
  assert.deepEqual(ui.orders.map((order) => order.checked), [true, true, false]);
  assert.equal(ui.summary.textContent, '2 pedidos seleccionados · $125.00');
  assert.equal(ui.button.disabled, false);
});

test('individual selection shows partial invoice and global selection', () => {
  const ui = setup();
  ui.orders[0].checked = true;
  ui.orders[0].listeners.change();
  assert.equal(ui.invoice.indeterminate, true);
  assert.equal(ui.invoice.checked, false);
  assert.equal(ui.selectAll.indeterminate, true);
  assert.equal(ui.button.disabled, false);
});

test('invoiced and uninvoiced selections contribute to the same payment total', () => {
  const ui = setup();
  ui.orders[0].checked = true;
  ui.orders[2].checked = true;
  ui.orders[2].listeners.change();
  assert.equal(ui.summary.textContent, '2 pedidos seleccionados · $135.25');
});

test('select all and clear all update invoice controls and payable total', () => {
  const ui = setup();
  ui.selectAll.checked = true;
  ui.selectAll.listeners.change();
  assert.equal(ui.summary.textContent, '3 pedidos seleccionados · $160.00');
  assert.equal(ui.invoice.checked, true);
  assert.equal(ui.invoice.indeterminate, false);
  ui.selectAll.checked = false;
  ui.selectAll.listeners.change();
  assert.equal(ui.button.disabled, true);
  assert.equal(ui.invoice.checked, false);
  assert.deepEqual(ui.orders.map((order) => order.checked), [false, false, false]);
});
