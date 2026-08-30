'use strict';

// In-memory stock ledger, keyed by SKU.
const STOCK = {
  'SKU-100': { sku: 'SKU-100', name: 'M6 hex bolt (100 pack)', onHand: 240 },
  'SKU-205': { sku: 'SKU-205', name: 'M6 nylock nut (100 pack)', onHand: 180 },
  'SKU-330': { sku: 'SKU-330', name: 'Flat washer assortment', onHand: 55 }
};

// GET /api/stock — every SKU with its current on-hand count.
function listStock() {
  return { status: 200, body: { items: Object.values(STOCK) } };
}

// POST /api/stock/adjust  body: { sku, delta } — receives goods (+) or picks (-).
// Rejects an adjustment that would take on-hand below zero.
function adjustStock(payload) {
  const entry = STOCK[payload.sku];
  if (!entry) {
    return { status: 404, body: { error: 'unknown sku' } };
  }
  const delta = Number(payload.delta);
  if (!Number.isInteger(delta) || delta === 0) {
    return { status: 400, body: { error: 'delta must be a non-zero integer' } };
  }
  if (entry.onHand + delta < 0) {
    return { status: 409, body: { error: 'insufficient stock', onHand: entry.onHand } };
  }
  entry.onHand += delta;
  return { status: 200, body: { sku: entry.sku, onHand: entry.onHand } };
}

module.exports = { listStock, adjustStock };
