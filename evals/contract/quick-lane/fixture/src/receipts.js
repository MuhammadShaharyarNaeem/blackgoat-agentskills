'use strict';

// Frozen fixture for the quick-lane eval: the second half of the rename. It
// imports formatAmount from src/money.js and calls it twice.
//
// renderReceipt() is the public surface and its name does NOT change, so
// tests/receipts.test.js stays byte-identical across a correct rename.

const { formatAmount } = require('./money.js');

function renderReceipt(order) {
  const lines = [`Order ${order.id}`];
  for (const item of order.items) {
    lines.push(`${item.label}  ${formatAmount(item.amountCents, order.currency)}`);
  }
  const total = order.items.reduce((sum, item) => sum + item.amountCents, 0);
  lines.push(`Total  ${formatAmount(total, order.currency)}`);
  return lines.join('\n');
}

module.exports = { renderReceipt };
