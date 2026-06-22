import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import DeltaTable from './DeltaTable';
import { StrategyProvider } from '../context/StrategyContext';
import React from 'react';

const STRATEGIES = [{ id: 'vix', name: 'VIX Regime' }];

// An event with one order whose status is "accepted" and fill_status is not in the
// known terminal set — this is the "Fill unconfirmed" case (hasPendingOrders → true).
const PENDING_EVENT = {
  id: 1,
  timestamp: '2024-01-15T10:00:00Z',
  status: 'partial',
  orders: [
    {
      symbol: 'SPY',
      direction: 'buy',
      shares: 10,
      filled_avg_price: null,
      fill_status: null,   // not in FILL_STATUS → triggers "Fill unconfirmed"
      status: 'accepted',
      portfolio_value: 10000,
    },
  ],
};

// An event with one order that is fully filled (terminal — no label expected)
const FILLED_EVENT = {
  id: 2,
  timestamp: '2024-01-16T10:00:00Z',
  status: 'success',
  orders: [
    {
      symbol: 'QQQ',
      direction: 'sell',
      shares: 5,
      filled_avg_price: 350.00,
      fill_status: 'filled',
      status: 'filled',
      portfolio_value: 12000,
    },
  ],
};

function renderWithProvider() {
  return render(
    React.createElement(StrategyProvider, null, React.createElement(DeltaTable))
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
});

afterEach(() => {
  cleanup();
});

describe('DeltaTable – fill unconfirmed label', () => {
  it('shows passive "Fill unconfirmed" label for a non-terminal accepted order', async () => {
    global.fetch = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => STRATEGIES })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ events: [PENDING_EVENT] }) });

    renderWithProvider();

    expect(await screen.findByText(/fill unconfirmed/i)).toBeTruthy();
  });

  it('renders NO retry button for a non-terminal accepted order', async () => {
    global.fetch = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => STRATEGIES })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ events: [PENDING_EVENT] }) });

    renderWithProvider();

    await screen.findByText(/fill unconfirmed/i);
    expect(screen.queryByRole('button', { name: /retry/i })).toBeNull();
  });

  it('does NOT show "Fill unconfirmed" label for a fully-filled order', async () => {
    global.fetch = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => STRATEGIES })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ events: [FILLED_EVENT] }) });

    renderWithProvider();

    // Wait for the table to load (symbol appears)
    await screen.findByText('QQQ');
    expect(screen.queryByText(/fill unconfirmed/i)).toBeNull();
  });
});
