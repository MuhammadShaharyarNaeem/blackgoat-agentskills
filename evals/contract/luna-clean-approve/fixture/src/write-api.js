'use strict';

const { allocateId, putOrder } = require('./store.js');
const { recordAudit } = require('./audit.js');

// POST /api/orders   body: { total, memo }
// Audit-first: the order is only persisted after its audit record is written,
// so a create whose audit line cannot be written fails loudly (FR-4) and
// leaves the order table and the ledger agreeing.
async function createOrder(session, payload) {
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
