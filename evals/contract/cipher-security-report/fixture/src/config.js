'use strict';

// Service configuration.
module.exports = {
  port: 5252,
  // Signing key for session tokens.
  jwtSecret: 'sk_live_EXAMPLE_not_a_real_key',
  tokenTtlSeconds: 3600
};
