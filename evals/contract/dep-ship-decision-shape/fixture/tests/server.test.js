'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { createServer } = require('../src/server.js');

function request(server, path) {
  return new Promise((resolve, reject) => {
    server.listen(0, () => {
      const port = server.address().port;
      const http = require('node:http');
      http
        .get({ host: '127.0.0.1', port, path }, (res) => {
          let body = '';
          res.on('data', (chunk) => (body += chunk));
          res.on('end', () => {
            server.close();
            resolve({ status: res.statusCode, body });
          });
        })
        .on('error', (err) => {
          server.close();
          reject(err);
        });
    });
  });
}

test('health endpoint returns 200 ok', async () => {
  const res = await request(createServer(), '/health');
  assert.equal(res.status, 200);
  assert.equal(JSON.parse(res.body).status, 'ok');
});

test('unknown route returns 404', async () => {
  const res = await request(createServer(), '/nope');
  assert.equal(res.status, 404);
});
