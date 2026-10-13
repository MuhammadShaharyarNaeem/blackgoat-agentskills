'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { capitalize } = require('../src/strings.js');

test('capitalize upper-cases the first character', () => {
  assert.equal(capitalize('hello world'), 'Hello world');
});

test('capitalize leaves an empty string empty', () => {
  assert.equal(capitalize(''), '');
});

test('capitalize rejects a non-string', () => {
  assert.throws(() => capitalize(42), TypeError);
});
