'use strict';

// Frozen fixture for the bugfix-batch-two-bugs eval: the DECOY, and correct.
//
// roundHalfUp() rounds a non-integer amount to the nearest whole unit, half
// away from zero - the rule money uses. It is really used: the /quote route in
// src/server.js rounds its shipping estimate through it.
//
// It is NOT used by computeTax(), which is defect B. Nothing here is broken:
// blaming this file is wrong, and editing it cannot change what computeTax()
// returns until computeTax() actually calls it.

function roundHalfUp(value) {
  if (!Number.isFinite(value)) {
    throw new TypeError('roundHalfUp requires a finite number');
  }
  if (value < 0) {
    return -Math.round(-value);
  }
  return Math.round(value);
}

module.exports = { roundHalfUp };
