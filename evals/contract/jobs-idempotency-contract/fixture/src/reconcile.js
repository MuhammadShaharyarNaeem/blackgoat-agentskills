'use strict';

// Payment reconciliation handler.
//
// A payment message arrives from the settlement queue and is applied to the
// in-memory ledger. The queue is at-least-once: it redelivers on any missing
// acknowledgement, so the same message id can arrive more than once.
//
// Public surface (frozen — callers depend on these three names and signatures):
//   applyPayment(message) -> { applied: boolean, total: number }
//   getLedger()           -> { entries: Array, total: number }
//   resetLedger()         -> undefined
//
// A message is: { id: string, accountId: string, amountCents: number }

const ledger = {
    entries: [],
    total: 0,
};

function applyPayment(message) {
    if (!message || typeof message.id !== 'string' || message.id === '') {
        throw new Error('message.id is required');
    }
    if (!Number.isInteger(message.amountCents)) {
        throw new Error('message.amountCents must be an integer');
    }

    ledger.entries.push({
        messageId: message.id,
        accountId: message.accountId,
        amountCents: message.amountCents,
    });
    ledger.total += message.amountCents;

    return { applied: true, total: ledger.total };
}

function getLedger() {
    return {
        entries: ledger.entries.map(function (entry) {
            return {
                messageId: entry.messageId,
                accountId: entry.accountId,
                amountCents: entry.amountCents,
            };
        }),
        total: ledger.total,
    };
}

function resetLedger() {
    ledger.entries.length = 0;
    ledger.total = 0;
}

module.exports = { applyPayment, getLedger, resetLedger };
