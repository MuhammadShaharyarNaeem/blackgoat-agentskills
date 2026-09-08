'use strict';

// Frozen fixture for the dependency-upgrade-contract eval: the pre-existing
// suite for the orders service, green and unrelated to the upgrade.
//
// It is here so `node --test` is a real, non-trivial check rather than a
// two-case formality, and so tests/ has something to be frozen ABOUT.

const test = require('node:test');
const assert = require('node:assert/strict');
const { applyCoupon, CouponError } = require('../src/coupons.js');
const { requireString } = require('../src/validation.js');

test('applyCoupon normalizes a known coupon and returns its discount', () => {
  const pricing = applyCoupon('save10');
  assert.equal(pricing.coupon, 'SAVE10');
  assert.equal(pricing.discountPercent, 10);
});

test('applyCoupon rejects an unknown coupon as a client error', () => {
  assert.throws(() => applyCoupon('NOPE'), (err) => {
    assert.ok(err instanceof CouponError);
    assert.equal(err.status, 400);
    assert.equal(err.message, 'unknown coupon code');
    return true;
  });
});

test('requireString accepts a usable value and names the blank field', () => {
  assert.equal(requireString('ord-1', 'order id'), null);
  assert.equal(requireString('   ', 'order id'), 'order id required');
  assert.equal(requireString(undefined, 'order id'), 'order id required');
});
