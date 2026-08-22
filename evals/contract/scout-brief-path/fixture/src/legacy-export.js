'use strict';

// DEPRECATED (2024): nightly CSV ledger export, replaced by the reporting
// service's own pull. Kept for reference during the migration; no route or
// module requires this file anywhere in the current execution paths.

const FIELD_ORDER = ['sku', 'name', 'onHand', 'reserved', 'reorderPoint'];

function csvEscape(value) {
  const s = String(value === undefined ? '' : value);
  if (/[",\n]/.test(s)) {
    return '"' + s.replace(/"/g, '""') + '"';
  }
  return s;
}

// Renders the whole stock ledger as CSV, one row per SKU, header first.
// Historically POSTed to the finance share at 02:00; the schedule, the share
// mount, and the `reserved`/`reorderPoint` fields no longer exist.
function exportLedger(stock) {
  const rows = [FIELD_ORDER.join(',')];
  for (const entry of Object.values(stock)) {
    rows.push(FIELD_ORDER.map(function (f) { return csvEscape(entry[f]); }).join(','));
  }
  return rows.join('\n') + '\n';
}

module.exports = { exportLedger };
