'use strict';

// Frozen fixture for the quick-lane eval: the RENAME TARGET.
//
// formatAmount() is defined and exported here, and used by src/receipts.js -
// those two files and nothing else. No test imports it directly, and no test
// in this fixture asserts on a negative amount, so the change the case asks
// for is exactly three files: this one, src/receipts.js, and a NEW unit test.

function formatAmount(cents, currency) {
  const sign = cents < 0 ? '-' : '';
  const abs = Math.abs(cents);
  const whole = Math.floor(abs / 100);
  const fraction = String(abs % 100).padStart(2, '0');
  return `${sign}${currency} ${whole}.${fraction}`;
}

module.exports = { formatAmount };
