'use strict';

const http = require('http');

const { listStock, adjustStock } = require('./inventory-api.js');

const PORT = 5353;

function send(res, status, body) {
  res.writeHead(status, { 'Content-Type': 'application/json' });
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
  if (req.method === 'GET' && req.url === '/api/stock') {
    const out = listStock();
    send(res, out.status, out.body);
    return;
  }

  if (req.method === 'POST' && req.url === '/api/stock/adjust') {
    const payload = await readBody(req);
    const out = adjustStock(payload);
    send(res, out.status, out.body);
    return;
  }

  send(res, 404, { error: 'no route' });
}

if (require.main === module) {
  http.createServer(handle).listen(PORT, function () {
    console.log('inventory listening on http://localhost:' + PORT);
  });
}

module.exports = { handle };
