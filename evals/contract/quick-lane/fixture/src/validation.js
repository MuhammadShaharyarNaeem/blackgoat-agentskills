'use strict';

// Frozen fixture for the quick-lane eval: unrelated, correct application code.
//
// requireString() is a guard helper: it rejects a non-string and a blank
// string, and returns null for a usable value. It is really used - the
// GET /orders/:id route in src/server.js calls it and answers 400 through it.
//
// It has nothing to do with the rename. It exists so `node --test` covers more
// than the change under test, and so the tree looks like a real service.

function requireString(value, fieldName) {
  if (typeof value !== 'string' || value.trim() === '') {
    return `${fieldName} required`;
  }
  return null;
}

module.exports = { requireString };
