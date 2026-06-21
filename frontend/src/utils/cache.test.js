import { describe, it, expect } from 'vitest';
import { cacheKey } from './cache';

describe('cacheKey', () => {
  it('returns prefix + view when no parts given', () => {
    expect(cacheKey('delta')).toBe('tradeinsight_delta');
  });

  it('appends one part with underscore separator', () => {
    expect(cacheKey('benchmark', 'SPY')).toBe('tradeinsight_benchmark_SPY');
    expect(cacheKey('delta', 'vix')).toBe('tradeinsight_delta_vix');
  });

  it('appends multiple parts joined by underscores', () => {
    expect(cacheKey('benchmark', 'SPY', 'vix')).toBe('tradeinsight_benchmark_SPY_vix');
  });

  it('filters out falsy parts (null/undefined/empty string)', () => {
    // null strategyId before first strategy loads → same as 2-arg call
    expect(cacheKey('benchmark', 'SPY', null)).toBe('tradeinsight_benchmark_SPY');
    expect(cacheKey('benchmark', 'SPY', undefined)).toBe('tradeinsight_benchmark_SPY');
    expect(cacheKey('benchmark', 'SPY', '')).toBe('tradeinsight_benchmark_SPY');
  });

  it('backward-compat: delta key matches old 2-arg form', () => {
    // Old: cacheKey('delta', strategyId) → 'tradeinsight_delta_vix'
    // New variadic: same result
    expect(cacheKey('delta', 'vix')).toBe('tradeinsight_delta_vix');
  });
});
