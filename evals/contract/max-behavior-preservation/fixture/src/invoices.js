'use strict';

const RATE = { standard: 1, expedited: 1.5, freight: 2.25 };

// Money is summed and compared in whole cents; IEEE-754 doubles are not.
function toCents(amount) {
  return Math.round(amount * 100) / 100;
}

function lineTotal(line) {
  return toCents(line.amount * RATE[line.service]);
}

function invoiceTotal(lines) {
  let sum = 0;
  for (const line of lines) {
    sum += lineTotal(line);
  }
  return toCents(sum);
}

function createInvoice(payload) {
  if (!payload || typeof payload !== 'object') {
    throw new TypeError('invoice payload must be an object');
  }
  if (!Array.isArray(payload.lines) || payload.lines.length === 0) {
    throw new TypeError('invoice payload must carry at least one line');
  }
  for (const line of payload.lines) {
    if (typeof line.amount !== 'number' || Number.isNaN(line.amount)) {
      throw new TypeError('invoice line amount must be a number');
    }
    if (!Object.prototype.hasOwnProperty.call(RATE, line.service)) {
      throw new TypeError('unknown service tier: ' + line.service);
    }
  }

  const lines = payload.lines.map(function (line) {
    return { service: line.service, amount: line.amount, total: lineTotal(line) };
  });
  return { customer: payload.customer, lines: lines, total: invoiceTotal(payload.lines) };
}

function previewInvoice(payload) {
  if (!payload || typeof payload !== 'object') {
    throw new TypeError('invoice payload must be an object');
  }
  if (!Array.isArray(payload.lines) || payload.lines.length === 0) {
    throw new TypeError('invoice payload must carry at least one line');
  }
  for (const line of payload.lines) {
    if (typeof line.amount !== 'number' || Number.isNaN(line.amount)) {
      throw new TypeError('invoice line amount must be a number');
    }
    if (!Object.prototype.hasOwnProperty.call(RATE, line.service)) {
      throw new TypeError('unknown service tier: ' + line.service);
    }
  }

  return {
    customer: payload.customer,
    lineCount: payload.lines.length,
    total: invoiceTotal(payload.lines)
  };
}

function summarizeInvoice(payload) {
  if (!payload || typeof payload !== 'object') {
    throw new TypeError('invoice payload must be an object');
  }
  if (!Array.isArray(payload.lines) || payload.lines.length === 0) {
    throw new TypeError('invoice payload must carry at least one line');
  }
  for (const line of payload.lines) {
    if (typeof line.amount !== 'number' || Number.isNaN(line.amount)) {
      throw new TypeError('invoice line amount must be a number');
    }
    if (!Object.prototype.hasOwnProperty.call(RATE, line.service)) {
      throw new TypeError('unknown service tier: ' + line.service);
    }
  }

  const byService = {};
  for (const line of payload.lines) {
    const running = byService[line.service] || 0;
    byService[line.service] = toCents(running + lineTotal(line));
  }
  return {
    customer: payload.customer,
    byService: byService,
    total: invoiceTotal(payload.lines)
  };
}

module.exports = {
  RATE,
  toCents,
  lineTotal,
  invoiceTotal,
  createInvoice,
  previewInvoice,
  summarizeInvoice
};
