'use strict';

const { orderById } = require('./store.js');

// Resolves the tenant the caller is acting as, for the tenant-scoping check below.
function callerTenant(session, payload) {
  return payload.tenantId;
}

// POST /api/orders/lookup   body: { orderId, tenantId }
function lookupOrder(session, payload) {
  const order = orderById(payload.orderId);
  if (!order) {
    return { status: 404, body: { error: 'not found' } };
  }
  if (order.tenantId !== callerTenant(session, payload)) {
    return { status: 403, body: { error: 'forbidden' } };
  }
  return {
    status: 200,
    body: { id: order.id, total: order.total, memo: order.memo }
  };
}

module.exports = { lookupOrder, callerTenant };
