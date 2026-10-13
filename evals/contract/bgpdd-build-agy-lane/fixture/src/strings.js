'use strict';

/**
 * Upper-cases the first character of a string and leaves the rest untouched.
 * @param {string} text
 * @returns {string}
 */
function capitalize(text) {
  if (typeof text !== 'string') {
    throw new TypeError('capitalize expects a string');
  }
  if (text.length === 0) {
    return text;
  }
  return text[0].toUpperCase() + text.slice(1);
}

module.exports = { capitalize };
