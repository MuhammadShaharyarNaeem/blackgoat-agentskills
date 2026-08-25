'use strict';

const test = require('node:test');
const assert = require('node:assert');

const {
  lineTotal,
  invoiceTotal,
  createInvoice,
  previewInvoice,
  summarizeInvoice
} = require('../src/invoices.js');

test('createInvoice rejects a non-object payload', () => {
  assert.throws(
    () => createInvoice(null),
    { name: 'TypeError', message: 'invoice payload must be an object' }
  );
});

test('previewInvoice rejects an empty line list', () => {
  assert.throws(
    () => previewInvoice({ customer: 'acme', lines: [] }),
    { name: 'TypeError', message: 'invoice payload must carry at least one line' }
  );
});

test('summarizeInvoice rejects a non-numeric amount', () => {
  assert.throws(
    () => summarizeInvoice({ customer: 'acme', lines: [{ amount: '3', service: 'standard' }] }),
    { name: 'TypeError', message: 'invoice line amount must be a number' }
  );
});

test('createInvoice rejects an unknown service tier', () => {
  assert.throws(
    () => createInvoice({ customer: 'acme', lines: [{ amount: 3, service: 'rocket' }] }),
    { name: 'TypeError', message: 'unknown service tier: rocket' }
  );
});

// 0.1 * 1.5 is 0.15000000000000002 in IEEE-754. The per-line rounding is what makes
// this 0.15. Removing it does not change the shape of the code's output - it changes
// the value.
test('an expedited line total is rounded to cents', () => {
  assert.strictEqual(lineTotal({ amount: 0.1, service: 'expedited' }), 0.15);
});

// 0.15 + 0.3 is 0.44999999999999996. The rounding applied AFTER the sum is what makes
// this 0.45, and it is not made redundant by the per-line rounding above.
test('an invoice total is rounded to cents after summing', () => {
  assert.strictEqual(
    invoiceTotal([
      { amount: 0.1, service: 'expedited' },
      { amount: 0.2, service: 'expedited' }
    ]),
    0.45
  );
});

test('createInvoice returns per-line totals and a grand total', () => {
  const invoice = createInvoice({
    customer: 'acme',
    lines: [
      { amount: 10, service: 'standard' },
      { amount: 4, service: 'freight' }
    ]
  });
  assert.strictEqual(invoice.customer, 'acme');
  assert.deepStrictEqual(invoice.lines.map((l) => l.total), [10, 9]);
  assert.strictEqual(invoice.total, 19);
});

test('previewInvoice reports the line count and the grand total', () => {
  const preview = previewInvoice({
    customer: 'acme',
    lines: [
      { amount: 10, service: 'standard' },
      { amount: 4, service: 'freight' }
    ]
  });
  assert.strictEqual(preview.lineCount, 2);
  assert.strictEqual(preview.total, 19);
});

test('summarizeInvoice groups totals by service tier', () => {
  const summary = summarizeInvoice({
    customer: 'acme',
    lines: [
      { amount: 10, service: 'standard' },
      { amount: 2, service: 'standard' },
      { amount: 4, service: 'freight' }
    ]
  });
  assert.deepStrictEqual(summary.byService, { standard: 12, freight: 9 });
  assert.strictEqual(summary.total, 21);
});
