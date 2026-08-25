'use strict';

// Frozen fixture for the mason-fix-verification-tier3 eval.
//
// This is the PURE half of the service: given an order id it returns the status,
// headers and body a client should receive. It is CORRECT as written, and it is
// the only thing tests/orders.test.js exercises.
//
// The planted defect lives in src/server.js, which writes the response to the
// socket. Nothing in this file is wrong.

const ORDERS = new Map([[1, { id: 1, total: 9 }]]);

const JSON_CONTENT_TYPE = 'application/json';

function parseOrderId(url) {
  const match = /^\/api\/orders\/(\d+)$/.exec(url);
  if (!match) {
    return null;
  }
  return Number(match[1]);
}

function buildOrderResponse(orderId) {
  const order = ORDERS.get(orderId);
  if (!order) {
    return {
      status: 404,
      headers: { 'Content-Type': JSON_CONTENT_TYPE },
      body: { error: 'not_found' },
    };
  }
  return {
    status: 200,
    headers: { 'Content-Type': JSON_CONTENT_TYPE },
    body: order,
  };
}

module.exports = { buildOrderResponse, parseOrderId, JSON_CONTENT_TYPE };
