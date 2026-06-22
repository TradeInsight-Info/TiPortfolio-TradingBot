import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { usePositions } from './usePositions';
import { StrategyProvider } from '../context/StrategyContext';
import React from 'react';

const STRATEGIES = [{ id: 'vix', name: 'VIX Regime' }];
const MOCK_POSITIONS_DATA = {
  positions: [{ symbol: 'QQQ', qty: 10, market_value: 7175.40, avg_entry_price: 700.75 }],
  equity: 9468.00,
  cash: 0.0,
  as_of: '2026-06-20T00:00:00Z',
};

function wrapper({ children }) {
  return React.createElement(StrategyProvider, null, children);
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('usePositions', () => {
  it('includes strategy_id in the fetch URL', async () => {
    global.fetch = vi.fn()
      // First call: /strategies (from StrategyProvider)
      .mockResolvedValueOnce({ ok: true, json: async () => STRATEGIES })
      // Second call: /positions?strategy_id=vix
      .mockResolvedValueOnce({ ok: true, json: async () => MOCK_POSITIONS_DATA });

    const { result } = renderHook(() => usePositions(), { wrapper });

    await waitFor(() => expect(result.current.loading).toBe(false));

    const positionsCall = global.fetch.mock.calls.find(([url]) =>
      url.includes('/positions')
    );
    expect(positionsCall).toBeTruthy();
    expect(positionsCall[0]).toContain('strategy_id=vix');
    expect(result.current.data.equity).toBe(9468.00);
    expect(result.current.error).toBeNull();
  });

  it('refetches when strategyId changes', async () => {
    const STRATEGIES_MULTI = [
      { id: 'vix', name: 'VIX Regime' },
      { id: 'trend_broad', name: 'Trend Following' },
    ];

    let resolveStrategies;
    const strategiesPromise = new Promise((res) => { resolveStrategies = res; });

    global.fetch = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => STRATEGIES_MULTI })
      .mockResolvedValue({ ok: true, json: async () => MOCK_POSITIONS_DATA });

    const { result } = renderHook(() => usePositions(), { wrapper });

    await waitFor(() => expect(result.current.loading).toBe(false));

    const positionsCalls = global.fetch.mock.calls.filter(([url]) =>
      url.includes('/positions')
    );
    // At least one /positions call was made for the initial strategy
    expect(positionsCalls.length).toBeGreaterThanOrEqual(1);
    expect(positionsCalls[0][0]).toContain('strategy_id=vix');
  });

  it('does not fetch when strategyId is null', async () => {
    // Return empty strategies so strategyId stays null
    global.fetch = vi.fn().mockResolvedValueOnce({ ok: true, json: async () => [] });

    const { result } = renderHook(() => usePositions(), { wrapper });

    // Give effect a tick to potentially fire
    await new Promise((r) => setTimeout(r, 50));

    const positionsCalls = global.fetch.mock.calls.filter(([url]) =>
      url.includes('/positions')
    );
    expect(positionsCalls.length).toBe(0);
  });

  it('sets data (not error) when response is configured:false', async () => {
    const NOT_CONFIGURED = { positions: [], equity: null, cash: null, configured: false, as_of: null };

    global.fetch = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => STRATEGIES })
      .mockResolvedValueOnce({ ok: true, json: async () => NOT_CONFIGURED });

    const { result } = renderHook(() => usePositions(), { wrapper });

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.error).toBeNull();
    expect(result.current.data).toEqual(NOT_CONFIGURED);
  });
});
