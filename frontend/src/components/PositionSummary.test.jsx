import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import PositionSummary from './PositionSummary';
import { StrategyProvider } from '../context/StrategyContext';
import React from 'react';

const STRATEGIES = [{ id: 'vix', name: 'VIX Regime' }];

function renderWithProvider() {
  return render(
    React.createElement(StrategyProvider, null, React.createElement(PositionSummary))
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('PositionSummary', () => {
  it('renders neutral message when configured:false — no error styling', async () => {
    global.fetch = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => STRATEGIES })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ positions: [], equity: null, cash: null, configured: false, as_of: null }),
      });

    renderWithProvider();

    await waitFor(() =>
      screen.getByText(/this strategy.s account isn.t connected yet/i)
    );

    // Must not render the red error class
    const msg = screen.getByText(/this strategy.s account isn.t connected yet/i);
    expect(msg.className).not.toContain('destructive');
  });

  it('renders the error banner on a real network failure (non-ok response)', async () => {
    global.fetch = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => STRATEGIES })
      .mockResolvedValueOnce({
        ok: false,
        status: 503,
        json: async () => ({ error: 'Alpaca is down' }),
      });

    renderWithProvider();

    await waitFor(() => screen.getByText(/could not load live positions/i));
    const banner = screen.getByText(/could not load live positions/i);
    expect(banner.className).toContain('destructive');
  });

  it('renders positions table for a connected account', async () => {
    global.fetch = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => STRATEGIES })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          positions: [{ symbol: 'QQQ', qty: 10, market_value: 7175.40, avg_entry_price: 700.75 }],
          equity: 9468.00,
          cash: 0.0,
          configured: true,
          as_of: '2026-06-20T00:00:00Z',
        }),
      });

    renderWithProvider();

    await waitFor(() => screen.getByText('QQQ'));
    expect(screen.getByText('10 shares')).toBeTruthy();
  });
});
