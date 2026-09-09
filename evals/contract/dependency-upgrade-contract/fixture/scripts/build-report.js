'use strict';

// Frozen fixture for the dependency-upgrade-contract eval: the ONLY call site
// of the dependency being upgraded.
//
// slugmaker 2.0.0 removes makeSlug in favour of toSlug (see
// node_modules/slugmaker/CHANGELOG.md). buildReport() is the public surface and
// its name does not change, so tests/build-report.test.js stays byte-identical
// across a correct upgrade.

const { makeSlug } = require('slugmaker');
const { renderReceipt } = require('../src/receipts.js');

function buildReport(order) {
  return {
    slug: makeSlug(order.title),
    body: renderReceipt(order)
  };
}

module.exports = { buildReport };
