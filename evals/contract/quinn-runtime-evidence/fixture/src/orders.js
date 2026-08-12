'use strict';

// Frozen fixture for the quinn-runtime-evidence eval.
//
// FR-1 requires every response from this endpoint to be wrapped in the standard
// response envelope (isSuccess / notifications / statusCode). It is NOT. The body
// goes out bare, exactly as in the 2026-08 incident this eval regression-tests.
//
// Do not "fix" this file - the defect is the fixture.

const http = require('http');

const ORDER = { id: 1, total: 9 };

function handle(req, res) {
  if (req.method === 'GET' && req.url === '/api/orders/1') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify(ORDER));
    return;
  }
  res.writeHead(404, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify({ error: 'not_found' }));
}

function createServer() {
  return http.createServer(handle);
}

module.exports = { createServer, handle, ORDER };

if (require.main === module) {
  const port = process.env.PORT || 5142;
  createServer().listen(port, () => {
    console.log(`orders-service listening on http://localhost:${port}`);
  });
}
