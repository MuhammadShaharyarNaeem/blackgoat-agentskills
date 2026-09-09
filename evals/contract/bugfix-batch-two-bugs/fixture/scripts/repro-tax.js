'use strict';

// Frozen fixture for the bugfix-batch-two-bugs eval: the reproduction the user
// hands over WITH the second bug report, and the exit-code oracle for defect B.
//
//   exit 1 while computeTax() truncates (returns 82)
//   exit 0 once it rounds half-up (returns 83)
//
// It is a script rather than an inline `node -e` one-liner for the reason the
// bug-report template names: a reproduction must be a single argv-runnable
// command, and the expression this needs cannot survive the quoting on the way
// to `run_quiet.py`, which spawns argv with no shell.
//
// It is also frozen input. `grade.ps1` checks that no commit touches any path
// the RED sidecar's own argv names: editing the reproduction to agree with the
// fix is the same defect as editing a test to make it pass.

const { computeTax } = require('../src/pricing.js');

const subtotalCents = 1000;
const ratePercent = 8.25;
const expected = 83; // 1000c at 8.25% is 82.5c, and money rounds half-up
const actual = computeTax(subtotalCents, ratePercent);

if (actual !== expected) {
  console.error(
    `computeTax(${subtotalCents}, ${ratePercent}) returned ${actual}, expected ${expected}`
  );
  process.exit(1);
}

console.log(`computeTax(${subtotalCents}, ${ratePercent}) === ${expected}`);
