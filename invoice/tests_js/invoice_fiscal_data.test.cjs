const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(
  path.join(__dirname, '../static/invoice/js/invoice_fiscal_data.js'), 'utf8',
);

function setup(fetch, initial = {}, jquery = false) {
  const fields = Object.fromEntries(
    ['rfc', 'razon_social', 'curp', 'billing_address'].map(
      (name) => [name, { value: initial[name] || '', disabled: false }],
    ),
  );
  const client = {
    value: '1', listeners: {},
    addEventListener(name, callback) { this.listeners[name] = callback; },
  };
  const submit = { disabled: false, type: 'submit' };
  const status = { textContent: '' };
  const form = {
    elements: Object.assign([...Object.values(fields), client, submit], {
      namedItem: (name) => name === 'client' ? client : fields[name],
    }),
    dataset: { fiscalDataUrl: '/billing/clients/0/fiscal-data/' },
    addEventListener() {},
  };
  const context = vm.createContext({
    fetch, form,
    ...(jquery ? { django: { jQuery: (element) => ({
      on: (name, callback) => { element.listeners[name] = callback; },
    }) } } : {}),
    document: { getElementById: () => status, addEventListener() {} },
  });
  vm.runInContext(source, context);
  const manager = vm.runInContext('new InvoiceFiscalDataManager(form)', context);
  return { manager, fields, client, submit, status };
}

function response(rfc) {
  return { ok: true, json: async () => ({ fiscal_data: {
    rfc, razon_social: 'Receptor SA de CV', curp: '', billing_address: 'Fiscal 123',
  } }) };
}

test('selecting a client fills fiscal fields and prevents submitting during loading', async () => {
  let finish;
  const ui = setup(() => new Promise((resolve) => { finish = resolve; }));
  const loading = ui.manager.load();
  assert.equal(ui.fields.rfc.disabled, true);
  assert.equal(ui.submit.disabled, true);
  finish(response('RFC-SELECTED'));
  await loading;
  assert.equal(ui.fields.rfc.value, 'RFC-SELECTED');
  assert.equal(ui.fields.razon_social.value, 'Receptor SA de CV');
  assert.equal(ui.fields.billing_address.value, 'Fiscal 123');
  assert.equal(ui.fields.rfc.disabled, false);
  assert.equal(ui.submit.disabled, false);
});

test('a slow response for a previous client cannot overwrite the current recipient', async () => {
  const pending = [];
  const ui = setup(() => new Promise((resolve) => pending.push(resolve)));
  const first = ui.manager.load();
  ui.client.value = '2';
  const second = ui.manager.load();
  pending[1](response('SECOND'));
  await second;
  pending[0](response('FIRST'));
  await first;
  assert.equal(ui.fields.rfc.value, 'SECOND');
});

test('clearing the client removes stale fiscal data and ignores a pending response', async () => {
  let finish;
  const ui = setup(() => new Promise((resolve) => { finish = resolve; }));
  const pending = ui.manager.load();
  ui.client.value = '';
  await ui.manager.load();
  finish(response('OLD'));
  await pending;
  assert.equal(ui.fields.rfc.value, '');
  assert.equal(ui.fields.billing_address.value, '');
  assert.equal(ui.fields.rfc.disabled, false);
  assert.equal(ui.submit.disabled, false);
});

test('failed loading clears the previous recipient and allows manual entry', async () => {
  const ui = setup(async () => ({ ok: false }), { rfc: 'PREVIOUS' });
  await ui.manager.load();
  assert.equal(ui.fields.rfc.value, '');
  assert.equal(ui.fields.rfc.disabled, false);
  assert.equal(ui.submit.disabled, false);
  assert.match(ui.status.textContent, /manualmente/);
});

test('initialization preserves server rendered values after an invalid submission', () => {
  const ui = setup(async () => response('DEFAULT'), { rfc: 'USER-EDITED' });
  assert.equal(ui.fields.rfc.value, 'USER-EDITED');
});

test('Django admin autocomplete changes fill the selected customer fiscal data', async () => {
  const ui = setup(async () => response('ADMIN-SELECTED'), {}, true);
  await ui.client.listeners.change();
  assert.equal(ui.fields.rfc.value, 'ADMIN-SELECTED');
  assert.equal(ui.fields.billing_address.value, 'Fiscal 123');
});
