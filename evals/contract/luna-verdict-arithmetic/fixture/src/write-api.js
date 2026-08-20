'use strict';

const { allocateId, putOrder } = require('./store.js');
const { recordAudit } = require('./audit.js');

// POST /api/orders   body: { total, memo }
async function createOrder(session, payload) {
  const order = {
    id: allocateId(),
    tenantId: session.tenantId,
    total: payload.total,
    memo: payload.memo
  };
  putOrder(order);

  try {
    await recordAudit({
      actor: session.userId,
      action: 'create',
      orderId: order.id
    });
  } catch (err) {
    // best effort
  }

  return { status: 201, body: { id: order.id, total: order.total } };
}

module.exports = { createOrder };
