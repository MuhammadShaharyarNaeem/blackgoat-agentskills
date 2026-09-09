'use strict';

// Offline stand-in for `npm audit` (dependency-upgrade-contract eval).
//
// An eval run has no registry, so this script is the project's declared audit
// command: it reads the versions pinned in package.json and checks them against
// the advisory database vendored beside it. Exit 1 when something matches, 0
// when nothing does - the same convention `npm audit` uses.
//
// Because it reads the PIN, running it before the bump and running it after
// produce different answers. That is the whole point: a before-capture with
// exit 1 could only have been taken while the old version was still pinned.

const fs = require('node:fs');
const path = require('node:path');

const root = path.join(__dirname, '..');
const manifest = JSON.parse(fs.readFileSync(path.join(root, 'package.json'), 'utf8'));
const advisories = JSON.parse(fs.readFileSync(path.join(__dirname, 'advisories.json'), 'utf8'));

const pinned = Object.assign({}, manifest.dependencies || {}, manifest.devDependencies || {});

function parts(version) {
  return String(version).replace(/^[\^~=v]+/, '').trim().split('.').map(function (n) {
    const parsed = parseInt(n, 10);
    return Number.isNaN(parsed) ? 0 : parsed;
  });
}

function compare(a, b) {
  const left = parts(a);
  const right = parts(b);
  for (let i = 0; i < 3; i++) {
    const l = left[i] || 0;
    const r = right[i] || 0;
    if (l !== r) { return l < r ? -1 : 1; }
  }
  return 0;
}

const findings = [];
for (const advisory of advisories.advisories) {
  const installed = pinned[advisory.package];
  if (!installed) { continue; }
  if (compare(installed, advisory.vulnerable_from) < 0) { continue; }
  if (compare(installed, advisory.patched_in) >= 0) { continue; }
  findings.push({ advisory: advisory, installed: installed });
}

console.log('offline audit - ' + Object.keys(pinned).length + ' package(s) pinned');
for (const name of Object.keys(pinned).sort()) {
  console.log('  ' + name + '@' + pinned[name]);
}
console.log('');

if (findings.length === 0) {
  console.log('found 0 vulnerabilities');
  process.exit(0);
}

for (const finding of findings) {
  const a = finding.advisory;
  console.log(a.severity + ': ' + a.title);
  console.log('  package:      ' + a.package + '@' + finding.installed);
  console.log('  vulnerable:   >= ' + a.vulnerable_from + ' < ' + a.patched_in);
  console.log('  patched in:   ' + a.patched_in);
  console.log('  advisory:     ' + a.id);
  console.log('');
}
console.log('found ' + findings.length + ' vulnerability(ies)');
process.exit(1);
