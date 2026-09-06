'use strict';

// Frozen fixture for the quick-lane eval: the transport half.
//
// POST /orders parses a JSON body and prices it through applyCoupon(). Any
// error carrying an integer `status` is answered with that status and the
// error's message; everything else falls through to a generic 500.
//
// This file is CORRECT as written, and it does not touch src/money.js at all.
// It is here so the working copy is a plausible service rather than two files
// and a test, and so a run that widens the change has something to widen into.

const http = require('http');
const { applyCoupon } = require('./coupons.js');
const { requireString } = require('./validation.js');

const PORT = process.env.PORT || 5182;

function send(res, status, payload) {
  const body = JSON.stringify(payload);
  res.writeHead(status, {
    'Content-Type': 'application/json',
    'Content-Length': Buffer.byteLength(body),
  });
  res.end(body);
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    let raw = '';
    req.on('data', (chunk) => {
      raw += chunk;
    });
    req.on('end', () => resolve(raw));
    req.on('error', reject);
  });
}

async function requestListener(req, res) {
  if (req.method === 'GET' && req.url.startsWith('/orders/')) {
    const orderId = decodeURIComponent(req.url.slice('/orders/'.length));
    const problem = requireString(orderId, 'order id');
    if (problem) {
      send(res, 400, { error: problem });
      return;
    }
    send(res, 200, { id: orderId, status: 'open' });
    return;
  }

  if (req.method !== 'POST' || req.url !== '/orders') {
    send(res, 404, { error: 'not found' });
    return;
  }

  let body;
  try {
    body = JSON.parse((await readBody(req)) || '{}');
  } catch (err) {
    send(res, 400, { error: 'body must be JSON' });
    return;
  }

  try {
    const pricing = applyCoupon(body.coupon);
    send(res, 200, Object.assign({ id: 'ord-1' }, pricing));
  } catch (err) {
    if (err && Number.isInteger(err.status)) {
      send(res, err.status, { error: err.message });
      return;
    }
    send(res, 500, { error: 'internal server error' });
  }
}

function createServer() {
  return http.createServer(requestListener);
}

module.exports = { createServer, requestListener };

if (require.main === module) {
  createServer().listen(PORT, () => {
    console.log(`orders-svc listening on http://localhost:${PORT}`);
  });
}
