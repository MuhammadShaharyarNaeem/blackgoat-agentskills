'use strict';

const test = require('node:test');
const assert = require('node:assert');

const { sessionFor, AUDIT } = require('../src/store.js');
const { lookupOrder } = require('../src/read-api.js');
const { createOrder } = require('../src/write-api.js');

const acme = sessionFor('tok-acme');

test('a caller reads an order in their own tenant', () => {
  const out = lookupOrder(acme, { orderId: 1, tenantId: 'acme' });
  assert.strictEqual(out.status, 200);
  assert.strictEqual(out.body.id, 1);
  assert.strictEqual(out.body.total, 9);
});

test('an unknown order id is a 404', () => {
  const out = lookupOrder(acme, { orderId: 4040, tenantId: 'acme' });
  assert.strictEqual(out.status, 404);
});

test('creating an order returns 201 and an integer id', async () => {
  const out = await createOrder(acme, { total: 12, memo: 'restock' });
  assert.strictEqual(out.status, 201);
  assert.ok(Number.isInteger(out.body.id));
});

test('creating an order appends an audit record', async () => {
  const before = AUDIT.length;
  await createOrder(acme, { total: 15, memo: 'restock' });
  assert.strictEqual(AUDIT.length, before + 1);
});
