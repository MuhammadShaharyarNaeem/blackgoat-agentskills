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

// Resolves the parsed body, or null when the body is not a JSON object: malformed
// JSON, a JSON scalar, and JSON `null` are all rejected rather than silently
// treated as an empty payload - the caller must be told their request was bad,
// and a `null` payload must never reach a handler.
function readBody(req) {
  return new Promise(function (resolve) {
    let raw = '';
    req.on('data', function (chunk) { raw += chunk; });
    req.on('end', function () {
      if (raw === '') {
        resolve({});
        return;
      }
      try {
        const parsed = JSON.parse(raw);
        if (parsed !== null && typeof parsed === 'object' && !Array.isArray(parsed)) {
          resolve(parsed);
        } else {
          resolve(null);
        }
      } catch (err) {
        resolve(null);
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

  const payload = await readBody(req);
  if (payload === null) {
    send(res, 400, { error: 'request body must be a JSON object' });
    return;
  }

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
}

if (require.main === module) {
  http.createServer(handle).listen(PORT, function () {
    console.log('orders listening on http://localhost:' + PORT);
  });
}

module.exports = { handle, send };
