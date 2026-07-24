'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { formatGreeting } = require('../src/greeting.js');

test('greets by name in English by default', () => {
  assert.equal(formatGreeting('Ada'), 'Hello, Ada!');
});

test('greets in Spanish when locale is es', () => {
  assert.equal(formatGreeting('Ada', 'es'), 'Hola, Ada!');
});

test('falls back to English for unknown locales', () => {
  assert.equal(formatGreeting('Ada', 'fr'), 'Hello, Ada!');
});

test('throws when name is missing', () => {
  assert.throws(() => formatGreeting(), /name is required/);
});
