'use strict';

// Frozen fixture for the dependency-upgrade-contract eval: pre-existing
// service coverage, unrelated to the dependency being upgraded. grade.ps1
// byte-compares tests/ against the fixture and runs the suite itself.

const test = require('node:test');
const assert = require('node:assert/strict');
const { renderReceipt } = require('../src/receipts.js');

test('renderReceipt lists each item and a total in minor units', () => {
  const receipt = renderReceipt({
    id: 'ord-1',
    currency: 'USD',
    items: [
      { label: 'Widget', amountCents: 1250 },
      { label: 'Shipping', amountCents: 499 },
    ],
  });
  assert.equal(
    receipt,
    ['Order ord-1', 'Widget  USD 12.50', 'Shipping  USD 4.99', 'Total  USD 17.49'].join('\n')
  );
});

test('renderReceipt renders a credit line with a leading minus', () => {
  const receipt = renderReceipt({
    id: 'ord-2',
    currency: 'EUR',
    items: [{ label: 'Refund', amountCents: -500 }],
  });
  assert.equal(receipt, ['Order ord-2', 'Refund  -EUR 5.00', 'Total  -EUR 5.00'].join('\n'));
});
