'use strict';

const test = require('node:test');
const assert = require('node:assert');

const { findOrder, buildBody } = require('../src/orders.js');

test('returns id for a known order', () => {
  const body = buildBody(findOrder(1));
  assert.strictEqual(body.id, 1);
});

test('returns total as a number', () => {
  const body = buildBody(findOrder(1));
  assert.strictEqual(
    typeof body.total,
    'number',
    `expected number, got ${typeof body.total}`
  );
});

test('returns undefined for an unknown order', () => {
  assert.strictEqual(findOrder(99), undefined);
});
