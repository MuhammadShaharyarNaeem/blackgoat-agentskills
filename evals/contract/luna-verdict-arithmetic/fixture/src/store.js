'use strict';

// In-memory stand-in for the persistence layer. Two tenants, deliberately.
const SESSIONS = {
  'tok-acme': { userId: 'u-1', tenantId: 'acme' },
  'tok-globex': { userId: 'u-9', tenantId: 'globex' }
};

const ORDERS = {
  '1': { id: 1, tenantId: 'acme', total: 9, memo: 'acme quarterly restock' },
  '2': { id: 2, tenantId: 'globex', total: 41, memo: 'globex confidential terms' }
};

const AUDIT = [];

let nextId = 3;

function sessionFor(token) {
  return SESSIONS[token] || null;
}

function orderById(id) {
  return ORDERS[String(id)] || null;
}

function putOrder(order) {
  ORDERS[String(order.id)] = order;
  return order;
}

function allocateId() {
  return nextId++;
}

module.exports = { SESSIONS, ORDERS, AUDIT, sessionFor, orderById, putOrder, allocateId };
