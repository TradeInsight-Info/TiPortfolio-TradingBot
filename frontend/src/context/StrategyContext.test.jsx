import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { StrategyProvider, useStrategy } from './StrategyContext';

// Minimal consumer component that renders the selector and active id
function StrategySelector() {
  const { strategies, strategyId, setStrategyId, loading, error } = useStrategy();
  return (
    <div>
      <span data-testid="active">{strategyId ?? 'none'}</span>
      <span data-testid="loading">{String(loading)}</span>
      {error && <span data-testid="error">{error}</span>}
      {strategies.length > 1 &&
        strategies.map((s) => (
          <button key={s.id} onClick={() => setStrategyId(s.id)}>
            {s.name}
          </button>
        ))}
    </div>
  );
}

const STRATEGIES = [
  { id: 'vix', name: 'VIX Regime' },
  { id: 'trend', name: 'Trend Following' },
];

beforeEach(() => {
  global.fetch = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => STRATEGIES,
  });
});

describe('StrategyProvider', () => {
  it('defaults to the first strategy from the API', async () => {
    render(
      <StrategyProvider>
        <StrategySelector />
      </StrategyProvider>
    );

    await waitFor(() =>
      expect(screen.getByTestId('active').textContent).toBe('vix')
    );
  });

  it('renders a button per strategy when multiple exist', async () => {
    render(
      <StrategyProvider>
        <StrategySelector />
      </StrategyProvider>
    );

    await waitFor(() => screen.getByText('VIX Regime'));
    expect(screen.getByText('Trend Following')).toBeTruthy();
  });

  it('switches strategyId when a strategy button is clicked', async () => {
    render(
      <StrategyProvider>
        <StrategySelector />
      </StrategyProvider>
    );

    await waitFor(() => screen.getByText('Trend Following'));
    fireEvent.click(screen.getByText('Trend Following'));

    expect(screen.getByTestId('active').textContent).toBe('trend');
  });

  it('renders no selector buttons when only one strategy exists', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => [STRATEGIES[0]],
    });

    render(
      <StrategyProvider>
        <StrategySelector />
      </StrategyProvider>
    );

    await waitFor(() =>
      expect(screen.getByTestId('active').textContent).toBe('vix')
    );
    // Single strategy → no buttons rendered by the selector guard
    expect(screen.queryByRole('button')).toBeNull();
  });

  it('exposes loading=false after fetch completes', async () => {
    render(
      <StrategyProvider>
        <StrategySelector />
      </StrategyProvider>
    );

    await waitFor(() =>
      expect(screen.getByTestId('loading').textContent).toBe('false')
    );
  });

  it('exposes error when /strategies returns non-ok status', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      json: async () => ({}),
    });

    render(
      <StrategyProvider>
        <StrategySelector />
      </StrategyProvider>
    );

    await waitFor(() =>
      expect(screen.getByTestId('loading').textContent).toBe('false')
    );
    expect(screen.getByTestId('error').textContent).toMatch(/500/);
    expect(screen.getByTestId('active').textContent).toBe('none');
  });

  it('exposes error on network failure and keeps strategies empty', async () => {
    global.fetch = vi.fn().mockRejectedValue(new Error('network down'));

    render(
      <StrategyProvider>
        <StrategySelector />
      </StrategyProvider>
    );

    await waitFor(() =>
      expect(screen.getByTestId('loading').textContent).toBe('false')
    );
    expect(screen.getByTestId('error').textContent).toBe('network down');
    expect(screen.getByTestId('active').textContent).toBe('none');
  });
});
