'use strict';

const { orderById } = require('./store.js');

// Resolves the tenant the caller is acting as. Always the authenticated
// session's tenant - never anything the request carries (FR-2).
function callerTenant(session) {
  return session.tenantId;
}

// POST /api/orders/lookup   body: { orderId }
function lookupOrder(session, payload) {
  const order = orderById(payload.orderId);
  if (!order) {
    return { status: 404, body: { error: 'not found' } };
  }
  if (order.tenantId !== callerTenant(session)) {
    return { status: 403, body: { error: 'forbidden' } };
  }
  return {
    status: 200,
    body: { id: order.id, total: order.total, memo: order.memo }
  };
}

module.exports = { lookupOrder, callerTenant };
