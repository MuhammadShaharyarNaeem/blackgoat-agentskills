'use strict';

// Already-implemented fixture module for the quinn-test-report-shape eval.
// Quinn writes and executes tests against this — she does not modify this file.

const crypto = require('crypto');

const TOKEN_TTL_MS = 15 * 60 * 1000; // 15 minutes, per FR-1

function generateResetToken(userId) {
  if (!userId) {
    throw new Error('userId is required');
  }
  const token = crypto.randomBytes(16).toString('hex'); // NFR-1: crypto-random, not Math.random
  const now = Date.now();
  return {
    userId,
    token,
    createdAt: now,
    expiresAt: now + TOKEN_TTL_MS,
    used: false,
  };
}

function isTokenValid(record, now = Date.now()) {
  if (!record || record.used) {
    return false;
  }
  return now < record.expiresAt;
}

function consumeToken(record, now = Date.now()) {
  if (!isTokenValid(record, now)) {
    return { ok: false, reason: 'invalid_or_expired' };
  }
  record.used = true;
  return { ok: true };
}

module.exports = { generateResetToken, isTokenValid, consumeToken, TOKEN_TTL_MS };
