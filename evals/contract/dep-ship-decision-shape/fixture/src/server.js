'use strict';

// Already-implemented fixture service for the dep-ship-decision-shape eval.
// Dep documents the shipping decision for this — he does not modify this file.

const http = require('http');

function handle(req, res) {
  if (req.url === '/health') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ status: 'ok' }));
    return;
  }
  res.writeHead(404, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify({ error: 'not_found' }));
}

function createServer() {
  return http.createServer(handle);
}

module.exports = { createServer, handle };

if (require.main === module) {
  const port = process.env.PORT || 3000;
  createServer().listen(port);
}
