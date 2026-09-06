'use strict';

// Frozen fixture for the dependency-upgrade-contract eval: ordinary service
// code, untouched by the upgrade under test.

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
