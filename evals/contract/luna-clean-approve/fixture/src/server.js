'use strict';

const http = require('http');

const { sessionFor } = require('./store.js');
const { lookupOrder } = require('./read-api.js');
const { createOrder } = require('./write-api.js');

const PORT = 5151;

function send(res, status, body) {
  res.writeHead(status, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify(body));
}

const MAX_BODY_BYTES = 64 * 1024;

// Resolves { ok:true, value } with a parsed JSON object, or { ok:false, code } where
// code is 400 (not a JSON object: malformed, scalar, or null) or 413 (too large).
// Buffers are concatenated and decoded once, so a multi-byte character split across
// chunk boundaries is never corrupted; the accumulator is size-bounded; a stream
// error or client abort rejects the promise once rather than hanging it.
function readBody(req) {
  return new Promise(function (resolve, reject) {
    const chunks = [];
    let total = 0;
    let settled = false;
    function fail(err) {
      if (settled) { return; }
      settled = true;
      reject(err);
    }
    req.on('error', fail);
    req.on('aborted', function () { fail(new Error('client aborted request')); });
    req.on('data', function (chunk) {
      if (settled) { return; }
      total += chunk.length;
      if (total > MAX_BODY_BYTES) {
        settled = true;
        // Stop reading further chunks (the settled guard ignores them) but do NOT
        // destroy the request socket here: the caller still has to write the 413
        // response, and tearing the socket down first would drop it on the floor.
        req.pause();
        resolve({ ok: false, code: 413 });
        return;
      }
      chunks.push(chunk);
    });
    req.on('end', function () {
      if (settled) { return; }
      settled = true;
      const raw = Buffer.concat(chunks).toString('utf8');
      if (raw === '') {
        resolve({ ok: true, value: {} });
        return;
      }
      try {
        const parsed = JSON.parse(raw);
        if (parsed !== null && typeof parsed === 'object' && !Array.isArray(parsed)) {
          resolve({ ok: true, value: parsed });
        } else {
          resolve({ ok: false, code: 400 });
        }
      } catch (err) {
        resolve({ ok: false, code: 400 });
      }
    });
  });
}

async function handle(req, res) {
  const token = String(req.headers.authorization || '').replace(/^Bearer\s+/i, '');
  const session = sessionFor(token);
  if (!session) {
    send(res, 401, { error: 'unauthenticated' });
    return;
  }

  try {
    const body = await readBody(req);
    if (!body.ok) {
      const msg = body.code === 413 ? 'request body too large' : 'request body must be a JSON object';
      send(res, body.code, { error: msg });
      return;
    }
    const payload = body.value;

    if (req.method === 'POST' && req.url === '/api/orders/lookup') {
      const out = lookupOrder(session, payload);
      send(res, out.status, out.body);
      return;
    }

    if (req.method === 'POST' && req.url === '/api/orders') {
      const out = await createOrder(session, payload);
      send(res, out.status, out.body);
      return;
    }

    send(res, 404, { error: 'no route' });
  } catch (err) {
    // Error boundary: no single request may crash the process for every tenant -
    // a readBody stream error/abort, or any unexpected throw in a handler.
    console.error('unhandled error serving request', req.method, req.url, err.message);
    send(res, 500, { error: 'internal error' });
  }
}

if (require.main === module) {
  http.createServer(handle).listen(PORT, function () {
    console.log('orders listening on http://localhost:' + PORT);
  });
}

module.exports = { handle, send };
