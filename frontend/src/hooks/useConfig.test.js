import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { useConfig } from './useConfig';

beforeEach(() => {
  global.fetch = vi.fn();
});

describe('useConfig', () => {
  it('returns parsed Number when initial_amount is present', async () => {
    global.fetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ initial_amount: 10000.5, recorded_at: '2024-01-15' }),
    });

    const { result } = renderHook(() => useConfig());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.initialAmount).toBe(10000.5);
    expect(result.current.error).toBeNull();
  });

  it('returns null when initial_amount is null', async () => {
    global.fetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ initial_amount: null }),
    });

    const { result } = renderHook(() => useConfig());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.initialAmount).toBeNull();
    expect(result.current.error).toBeNull();
  });

  it('sets error on non-2xx response', async () => {
    global.fetch.mockResolvedValueOnce({
      ok: false,
      status: 500,
      json: async () => ({ error: 'Internal server error' }),
    });

    const { result } = renderHook(() => useConfig());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.error).toBe('Internal server error');
    expect(result.current.initialAmount).toBeNull();
  });

  it('sets error on network failure', async () => {
    global.fetch.mockRejectedValueOnce(new Error('Network failure'));

    const { result } = renderHook(() => useConfig());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.error).toBe('Network failure');
    expect(result.current.initialAmount).toBeNull();
  });
});
