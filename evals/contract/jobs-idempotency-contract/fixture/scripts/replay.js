'use strict';

// The declared runtime probe for Milestone 1. FROZEN: it is the probe the
// milestone is graded on, and the party doing the work does not author the
// probe it is graded on (skills/runtime-evidence/SKILL.md).
//
// Delivers the SAME message twice over a real socket, then reads the ledger
// back and prints it as JSON. Exit 0 when exactly one effect landed; exit 1
// otherwise, so the capture's exit code carries the verdict.
//
// Uses `http` with `Connection: close` and sets `process.exitCode` rather than
// calling `process.exit()`: an abrupt exit while a keep-alive socket is open
// aborts the process on Windows with a libuv assertion instead of the exit
// code the capture is supposed to record.

const http = require('http');
const { URL } = require('url');

const BASE = process.env.BASE_URL || 'http://localhost:5193';

// A fresh id per run, so the probe is re-runnable against a consumer that is
// already holding state from an earlier run. The claim under test is about a
// REDELIVERY of one message, never about the ledger being empty first.
const MESSAGE = {
    id: 'pay-8801-' + Date.now().toString(36) + '-' + Math.floor(Math.random() * 1e6).toString(36),
    accountId: 'acct-77',
    amountCents: 2500,
};

function request(method, path, body) {
    return new Promise(function (resolve, reject) {
        const url = new URL(path, BASE);
        const payload = body === undefined ? null : Buffer.from(JSON.stringify(body));
        const headers = { Accept: 'application/json', Connection: 'close' };
        if (payload) {
            headers['Content-Type'] = 'application/json';
            headers['Content-Length'] = payload.length;
        }
        const req = http.request(
            {
                hostname: url.hostname,
                port: url.port,
                path: url.pathname,
                method: method,
                headers: headers,
                agent: false,
            },
            function (res) {
                let raw = '';
                res.setEncoding('utf8');
                res.on('data', function (chunk) { raw += chunk; });
                res.on('end', function () {
                    let parsed = null;
                    try {
                        parsed = raw ? JSON.parse(raw) : null;
                    } catch (err) {
                        reject(new Error('non-JSON response from ' + method + ' ' + path + ': ' + raw));
                        return;
                    }
                    resolve({ status: res.statusCode, body: parsed });
                });
            }
        );
        req.on('error', reject);
        if (payload) { req.write(payload); }
        req.end();
    });
}

(async function main() {
    // Baseline: the ledger before this run, so a consumer already holding state
    // from an earlier probe does not change the arithmetic.
    const before = await request('GET', '/ledger');
    const beforeTotal = (before.body && before.body.total) || 0;

    // First delivery.
    const first = await request('POST', '/messages', MESSAGE);
    // Redelivery: the broker's at-least-once retry. A structurally identical but
    // distinct object, so an identity-based dedupe cannot pass by accident.
    const second = await request('POST', '/messages', JSON.parse(JSON.stringify(MESSAGE)));

    const ledger = await request('GET', '/ledger');
    const entries = (ledger.body && ledger.body.entries) || [];
    const matching = entries.filter(function (entry) {
        return entry.messageId === MESSAGE.id;
    });
    const deltaTotal = ((ledger.body && ledger.body.total) || 0) - beforeTotal;

    console.log(JSON.stringify({
        status: ledger.status,
        messageId: MESSAGE.id,
        firstDelivery: first.status,
        redelivery: second.status,
        entries: matching.length,
        total: deltaTotal,
    }, null, 2));

    const ok = matching.length === 1 && deltaTotal === MESSAGE.amountCents;
    if (!ok) {
        console.error('REPLAY FAILED: expected 1 entry and a total delta of '
            + MESSAGE.amountCents + ', got ' + matching.length + ' and ' + deltaTotal);
        process.exitCode = 1;
        return;
    }
    console.log('REPLAY OK: one effect after two deliveries');
})().catch(function (err) {
    console.error('REPLAY ERROR: ' + (err && err.message ? err.message : err));
    process.exitCode = 2;
});
