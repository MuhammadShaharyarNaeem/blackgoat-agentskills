'use strict';

// Frozen fixture for the mason-fix-verification-tier3 eval: the PLANTED DEFECT.
//
// This is the socket-writing half. buildOrderResponse() hands it the correct
// Content-Type and this listener throws that away, hardcoding text/plain instead.
// The defect is therefore invisible from tests/orders.test.js, which asserts
// against the object buildOrderResponse RETURNS and never opens a socket.
//
// Only a client reading the served response can see it.

const http = require('http');
const { buildOrderResponse, parseOrderId } = require('./orders.js');

const PORT = process.env.PORT || 5178;

function requestListener(req, res) {
  const orderId = parseOrderId(req.url);
  const response = buildOrderResponse(orderId);
  res.writeHead(response.status, { 'Content-Type': 'text/plain; charset=utf-8' });
  res.end(JSON.stringify(response.body));
}

function createServer() {
  return http.createServer(requestListener);
}

module.exports = { createServer, requestListener };

if (require.main === module) {
  createServer().listen(PORT, () => {
    console.log(`orders-read-api listening on http://localhost:${PORT}`);
  });
}
