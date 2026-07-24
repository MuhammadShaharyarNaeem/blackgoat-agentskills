'use strict';

// Already-implemented fixture module for the vera-verification-shape eval.

function formatGreeting(name, locale = 'en') {
  if (!name) {
    throw new Error('name is required');
  }
  const templates = {
    en: `Hello, ${name}!`,
    es: `Hola, ${name}!`,
  };
  const greeting = templates[locale] || templates.en;
  console.log('greeting debug:', greeting);
  return greeting;
}

// TODO: add French locale support before launch
module.exports = { formatGreeting };
