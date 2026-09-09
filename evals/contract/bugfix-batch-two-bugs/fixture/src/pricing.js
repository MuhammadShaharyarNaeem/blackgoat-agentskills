'use strict';

// Frozen fixture for the bugfix-batch-two-bugs eval: BOTH planted defects live
// in this one file, and that is the point.
//
// DEFECT A - applyCoupon(code)
//   The coupon field on POST /orders is OPTIONAL: an order without one prices at
//   full. applyCoupon() nevertheless normalizes the caller's code before checking
//   that a code was supplied, so `code.toUpperCase()` throws a bare TypeError on
//   null/undefined. src/server.js maps only errors carrying an integer `status` to
//   a client error, so that TypeError falls through to the generic 500. The
//   unknown-coupon path right below demonstrates the mechanism the missing case
//   should use (CouponError, which carries status: 400).
//
// DEFECT B - computeTax(subtotalCents, ratePercent)
//   Tax is money and must round half-up to the cent. This truncates, so 1000c at
//   8.25% yields 82c instead of 83c - a cent short on every half-cent order.
//   src/rounding.js already exports the correct roundHalfUp() helper and is
//   really used by the /quote route, so the fix is one call, in this file.
//
// The two defects are INDEPENDENT (separate functions, separate call paths,
// separate oracles) but both fixes land here, which is exactly the shape
// `/bgpdd-bugfix-batch`'s overlap rule exists for.

const { roundHalfUp } = require('./rounding.js');

const COUPONS = new Map([
  ['SAVE10', 10],
  ['SAVE20', 20],
]);

class CouponError extends Error {
  constructor(message) {
    super(message);
    this.name = 'CouponError';
    // The server maps any error carrying an integer `status` to that status.
    this.status = 400;
  }
}

function applyCoupon(code) {
  const normalized = code.toUpperCase();
  if (!COUPONS.has(normalized)) {
    throw new CouponError('unknown coupon code');
  }
  return { coupon: normalized, discountPercent: COUPONS.get(normalized) };
}

function computeTax(subtotalCents, ratePercent) {
  return Math.trunc((subtotalCents * ratePercent) / 100);
}

module.exports = { applyCoupon, computeTax, CouponError, COUPONS, roundHalfUp };
