'use strict';

// Frozen fixture for the verify-matrix-derivation eval: correct application code.
//
// requireString() is a guard helper: it rejects a non-string and a blank
// string, and returns null for a usable value. It is really used - the
// GET /orders/:id route in src/server.js calls it and answers 400 through it.
//
// It backs the baseline's EC-01 and RR-01 cases, both outside this case's scope.

function requireString(value, fieldName) {
  if (typeof value !== 'string' || value.trim() === '') {
    return `${fieldName} required`;
  }
  return null;
}

module.exports = { requireString };
