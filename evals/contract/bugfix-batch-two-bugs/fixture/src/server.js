'use strict';

// Frozen fixture for the bugfix-batch-two-bugs eval: the transport half, and
// CORRECT as written. Both defects are in src/pricing.js.
//
// POST /orders prices a JSON body through applyCoupon() and computeTax(). Any
// error carrying an integer `status` is answered with that status; everything
// else falls through to a generic 500 - which is what defect A's bare TypeError
// currently takes.
//
// GET /quote?cents=N is the real user of src/rounding.js, so the decoy is not
// dead code.

const http = require('http');
const { applyCoupon, computeTax } = require('./pricing.js');
const { roundHalfUp } = require('./rounding.js');

const PORT = process.env.PORT || 5194;
const TAX_RATE_PERCENT = 8.25;

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
  if (req.method === 'GET' && req.url.startsWith('/quote')) {
    const raw = Number(new URL(req.url, 'http://localhost').searchParams.get('cents'));
    if (!Number.isFinite(raw)) {
      send(res, 400, { error: 'cents must be a number' });
      return;
    }
    send(res, 200, { shippingCents: roundHalfUp(raw / 3) });
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

  const subtotalCents = Number.isFinite(body.subtotalCents) ? body.subtotalCents : 1000;

  try {
    const pricing = applyCoupon(body.coupon);
    send(res, 200, Object.assign({ id: 'ord-1', subtotalCents }, pricing, {
      taxCents: computeTax(subtotalCents, TAX_RATE_PERCENT),
    }));
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
    console.log(`checkout-svc listening on http://localhost:${PORT}`);
  });
}
