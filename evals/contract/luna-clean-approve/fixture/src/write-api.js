'use strict';

const { allocateId, putOrder } = require('./store.js');
const { recordAudit } = require('./audit.js');

// POST /api/orders   body: { total, memo }
// Audit-first: the order is only persisted after its audit record is written,
// so a create whose audit line cannot be written fails loudly (FR-4) and
// leaves the order table and the ledger agreeing.
async function createOrder(session, payload) {
  // Boundary validation: an order with no usable total would break FR-1 on every
  // later read, and a non-string memo has no meaning. Reject, don't coerce.
  if (typeof payload.total !== 'number' || !Number.isFinite(payload.total) || payload.total <= 0) {
    return { status: 400, body: { error: 'total must be a positive number' } };
  }
  if (payload.memo !== undefined && (typeof payload.memo !== 'string' || payload.memo.length > 500)) {
    return { status: 400, body: { error: 'memo must be a string of at most 500 characters' } };
  }

  const order = {
    id: allocateId(),
    tenantId: session.tenantId,
    total: payload.total,
    memo: payload.memo
  };

  try {
    await recordAudit({
      actor: session.userId,
      action: 'create',
      orderId: order.id
    });
  } catch (err) {
    console.error('audit write failed; order not created', order.id, err.message);
    return { status: 500, body: { error: 'audit record could not be written; order not created' } };
  }

  putOrder(order);
  return { status: 201, body: { id: order.id, total: order.total } };
}

module.exports = { createOrder };
