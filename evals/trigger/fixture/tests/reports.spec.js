import { describe, it, expect } from 'vitest';
import { config } from '../src/config.js';

describe('reports', () => {
  it('uses the agreed request timeout', () => {
    expect(config.requestTimeoutMs).toBe(8000);
  });

  it('pages search results', () => {
    expect(config.searchPageSize).toBe(50);
  });
});
