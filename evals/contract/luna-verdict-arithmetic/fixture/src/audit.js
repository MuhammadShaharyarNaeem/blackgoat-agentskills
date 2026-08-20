'use strict';

const { AUDIT } = require('./store.js');

// Appends one audit record. Rejects when the record cannot be attributed to an
// actor: an unattributable audit line is worse than no audit line at all.
async function recordAudit(entry) {
  if (!entry || !entry.actor) {
    throw new Error('audit entry requires an actor');
  }
  AUDIT.push({ actor: entry.actor, action: entry.action, orderId: entry.orderId });
  return AUDIT.length;
}

module.exports = { recordAudit };
