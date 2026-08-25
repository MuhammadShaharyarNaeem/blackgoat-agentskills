'use strict';

const http = require('http');

const PORT = 5143;

const ORDERS = {
  '1': { id: 1, total: 9 },
  '2': { id: 2, total: 41 }
};

function findOrder(id) {
  return ORDERS[String(id)];
}

// Serializes an order for the API response.
function buildBody(order) {
  return { id: order.id, total: String(order.total) };
}

function handle(req, res) {
  const match = /^\/api\/orders\/(\d+)$/.exec(req.url || '');
  if (!match) {
    res.writeHead(404, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ error: 'not found' }));
    return;
  }
  const order = findOrder(match[1]);
  if (!order) {
    res.writeHead(404, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ error: 'not found' }));
    return;
  }
  res.writeHead(200, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify(buildBody(order)));
}

if (require.main === module) {
  http.createServer(handle).listen(PORT, () => {
    console.log(`orders listening on http://localhost:${PORT}`);
  });
}

module.exports = { findOrder, buildBody, handle };
