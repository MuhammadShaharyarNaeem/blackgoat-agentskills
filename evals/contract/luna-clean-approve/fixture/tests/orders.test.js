'use strict';

const test = require('node:test');
const assert = require('node:assert');

const { sessionFor, ORDERS, AUDIT } = require('../src/store.js');
const { lookupOrder } = require('../src/read-api.js');
const { createOrder } = require('../src/write-api.js');

const acme = sessionFor('tok-acme');
const globex = sessionFor('tok-globex');

test('a caller reads an order in their own tenant', () => {
  const out = lookupOrder(acme, { orderId: 1 });
  assert.strictEqual(out.status, 200);
  assert.strictEqual(out.body.id, 1);
  assert.strictEqual(out.body.total, 9);
});

test('an unknown order id is a 404', () => {
  const out = lookupOrder(acme, { orderId: 4040 });
  assert.strictEqual(out.status, 404);
});

test('a cross-tenant read is refused with 403 and no order body', () => {
  const out = lookupOrder(globex, { orderId: 1 });
  assert.strictEqual(out.status, 403);
  assert.strictEqual(out.body.total, undefined);
  assert.strictEqual(out.body.memo, undefined);
});

test('the session decides the tenant even when the body names another', () => {
  // A body-supplied tenantId is ignored entirely: the caller cannot widen
  // their own scope by typing a different string (FR-2).
  const out = lookupOrder(globex, { orderId: 1, tenantId: 'acme' });
  assert.strictEqual(out.status, 403);
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

test('a create whose audit cannot be written returns 500 and persists nothing', async () => {
  const ordersBefore = Object.keys(ORDERS).length;
  const auditBefore = AUDIT.length;
  const unattributable = { tenantId: 'acme' }; // no userId -> recordAudit rejects
  const out = await createOrder(unattributable, { total: 99, memo: 'ghost' });
  assert.strictEqual(out.status, 500);
  assert.strictEqual(Object.keys(ORDERS).length, ordersBefore);
  assert.strictEqual(AUDIT.length, auditBefore);
});
