'use strict';

const test = require('node:test');
const assert = require('node:assert');

const { EventEmitter } = require('node:events');

const { sessionFor, ORDERS, AUDIT } = require('../src/store.js');
// sessionFor is exercised directly by the prototype-chain test below.
const { lookupOrder } = require('../src/read-api.js');
const { createOrder } = require('../src/write-api.js');
const { handle } = require('../src/server.js');

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

test('a lookup with no orderId is a 400, not a 404 guess', () => {
  const out = lookupOrder(acme, {});
  assert.strictEqual(out.status, 400);
});

test('a lookup whose orderId is a non-primitive is a 400, not a crash', () => {
  for (const bad of [{ toString: 'x' }, { a: 1 }, [1, 2], true]) {
    const out = lookupOrder(acme, { orderId: bad });
    assert.strictEqual(out.status, 400);
  }
});

test('the handler error boundary returns 500 on a request stream error, not a crash', async () => {
  // Drive handle() with a request whose body stream errors: the readBody promise
  // rejects, and the catch must convert it to 500 rather than an unhandled rejection.
  const req = new EventEmitter();
  req.method = 'POST';
  req.url = '/api/orders/lookup';
  req.headers = { authorization: 'Bearer tok-acme' };
  let status = null;
  const res = {
    writeHead(code) { status = code; },
    end() {}
  };
  const done = handle(req, res);
  req.emit('error', new Error('socket blew up'));
  await done;
  assert.strictEqual(status, 500);
});

test('a create with a missing or non-positive total is a 400 and persists nothing', async () => {
  const ordersBefore = Object.keys(ORDERS).length;
  for (const bad of [{}, { total: 0 }, { total: -5 }, { total: 'twelve' }, { total: NaN }]) {
    const out = await createOrder(acme, bad);
    assert.strictEqual(out.status, 400);
  }
  assert.strictEqual(Object.keys(ORDERS).length, ordersBefore);
});

test('a create with a non-string memo is a 400', async () => {
  const out = await createOrder(acme, { total: 5, memo: { note: 'x' } });
  assert.strictEqual(out.status, 400);
});

test('a prototype-chain token resolves to no session, not an inherited member', () => {
  for (const key of ['__proto__', 'constructor', 'toString', 'hasOwnProperty']) {
    assert.strictEqual(sessionFor(key), null);
  }
});

test('a prototype-chain order id resolves to no order (404), not a truthy non-order', () => {
  const out = lookupOrder(acme, { orderId: '__proto__' });
  assert.strictEqual(out.status, 404);
});
