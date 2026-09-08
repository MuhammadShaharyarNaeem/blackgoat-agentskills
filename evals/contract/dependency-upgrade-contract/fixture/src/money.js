'use strict';

// Frozen fixture for the dependency-upgrade-contract eval: ordinary service
// code, untouched by the upgrade under test. It exists so `node --test` is a
// real suite rather than a two-case formality.

function formatAmount(cents, currency) {
  const sign = cents < 0 ? '-' : '';
  const abs = Math.abs(cents);
  const whole = Math.floor(abs / 100);
  const fraction = String(abs % 100).padStart(2, '0');
  return `${sign}${currency} ${whole}.${fraction}`;
}

module.exports = { formatAmount };
