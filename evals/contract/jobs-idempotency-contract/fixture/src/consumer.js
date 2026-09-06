'use strict';

// The settlement consumer, fronted by HTTP so a replay can be delivered from
// outside this process:
//
//   POST /messages  { id, accountId, amountCents }  -> 200 { applied, total }
//   GET  /ledger                                    -> 200 { entries, total }
//
// The transport is a stand-in for the broker. What matters for verification is
// that a message crosses a socket to reach the handler, so a redelivery is a
// real second delivery and not a second function call in the test's own process.

const http = require('http');
const { applyPayment, getLedger } = require('./reconcile');

const PORT = Number(process.env.PORT || 5193);

function readBody(req) {
    return new Promise(function (resolve, reject) {
        let raw = '';
        req.on('data', function (chunk) { raw += chunk; });
        req.on('end', function () {
            try {
                resolve(raw ? JSON.parse(raw) : {});
            } catch (err) {
                reject(err);
            }
        });
        req.on('error', reject);
    });
}

function send(res, status, payload) {
    const body = JSON.stringify(payload);
    res.writeHead(status, {
        'Content-Type': 'application/json',
        'Content-Length': Buffer.byteLength(body),
    });
    res.end(body);
}

const server = http.createServer(async function (req, res) {
    try {
        if (req.method === 'POST' && req.url === '/messages') {
            const message = await readBody(req);
            const result = applyPayment(message);
            send(res, 200, result);
            return;
        }
        if (req.method === 'GET' && req.url === '/ledger') {
            send(res, 200, getLedger());
            return;
        }
        send(res, 404, { error: 'not found' });
    } catch (err) {
        send(res, 400, { error: String(err && err.message ? err.message : err) });
    }
});

server.listen(PORT, function () {
    console.log('settlement consumer listening on http://localhost:' + PORT);
});
