'use strict';

// Prints the slug of a fixed title from a separate node process. Exits non-zero
// until src/strings.js exports slugify.
const { slugify } = require('../src/strings.js');

if (typeof slugify !== 'function') {
  console.error('slugify is not exported from src/strings.js');
  process.exit(1);
}
console.log(slugify('  Hello, World! 2026  '));
