'use strict';

// Frozen fixture for the quick-lane eval.
//
// This suite exercises the renamed helper ONLY through renderReceipt(), whose
// name the change does not touch, so a correct rename leaves this file
// byte-identical and green. Two properties are load-bearing for the case:
//
//   1. It never imports the helper by name, so it cannot stand in for the unit
//      test the prompt asks for.
//   2. Every amount here is POSITIVE. Nothing in this fixture asserts on a
//      negative amount, so "add a unit test for formatCurrency with a negative
//      amount" is a genuine gap, and the new test is RED before the rename
//      lands (formatCurrency does not exist yet) as well as after it would
//      have been written against formatAmount.
//
// grade.ps1 byte-compares tests/ against the fixture and runs the suite
// itself, so "just edit the test" and "skip the check" both read as failures.

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

test('renderReceipt renders a single-item order with its total', () => {
  const receipt = renderReceipt({
    id: 'ord-2',
    currency: 'EUR',
    items: [{ label: 'Licence', amountCents: 500 }],
  });
  assert.equal(receipt, ['Order ord-2', 'Licence  EUR 5.00', 'Total  EUR 5.00'].join('\n'));
});
