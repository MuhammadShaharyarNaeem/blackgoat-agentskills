'use strict';

const http = require('http');
const crypto = require('crypto');

const config = require('./config.js');
const { listNotes, createNote } = require('./notes-api.js');

// Token format: "<userId>.<hex signature>", signature = HMAC-SHA256(userId).
function verifyToken(token) {
  const dot = token.indexOf('.');
  if (dot <= 0) {
    return null;
  }
  const userId = token.slice(0, dot);
  const signature = token.slice(dot + 1);
  const expected = crypto
    .createHmac('sha256', config.jwtSecret)
    .update(userId)
    .digest('hex');
  if (signature.length !== expected.length) {
    return null;
  }
  const ok = crypto.timingSafeEqual(Buffer.from(signature), Buffer.from(expected));
  return ok ? userId : null;
}

function send(res, status, body) {
  res.writeHead(status, {
    'Content-Type': 'application/json',
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Headers': 'Authorization, Content-Type'
  });
  res.end(JSON.stringify(body));
}

function readBody(req) {
  return new Promise(function (resolve) {
    let raw = '';
    req.on('data', function (chunk) { raw += chunk; });
    req.on('end', function () {
      try {
        resolve(JSON.parse(raw || '{}'));
      } catch (err) {
        resolve({});
      }
    });
  });
}

async function handle(req, res) {
  if (req.method === 'OPTIONS') {
    send(res, 204, {});
    return;
  }

  const token = String(req.headers.authorization || '').replace(/^Bearer\s+/i, '');
  const userId = verifyToken(token);
  if (!userId) {
    send(res, 401, { error: 'unauthenticated' });
    return;
  }

  if (req.method === 'GET' && req.url === '/api/notes') {
    const out = listNotes(userId);
    send(res, out.status, out.body);
    return;
  }

  if (req.method === 'POST' && req.url === '/api/notes') {
    const payload = await readBody(req);
    const out = createNote(userId, payload);
    send(res, out.status, out.body);
    return;
  }

  send(res, 404, { error: 'no route' });
}

if (require.main === module) {
  http.createServer(handle).listen(config.port, function () {
    console.log('notes listening on http://localhost:' + config.port);
  });
}

module.exports = { handle };
