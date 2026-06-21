import { useState, useEffect } from "react";
import { cacheKey, readCache, writeCache, clearCache } from '../utils/cache';
import { useStrategy } from '../context/StrategyContext';

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '/api';

export function useBenchmark(ticker) {
  const { strategyId } = useStrategy();

  const key = cacheKey('benchmark', ticker, strategyId);

  // Initialise from cache so the chart renders immediately on repeat visits
  const cached = readCache(key);
  const [data, setData]       = useState(cached ?? null);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState(null);

  // Encode '+' in composite ticker for URL query string
  const encodedTicker = encodeURIComponent(ticker);

  useEffect(() => {
    // Guard: don't fire until a strategy is selected
    if (!strategyId) return;

    let cancelled = false;

    setLoading(true);
    setError(null);

    const currentKey = cacheKey('benchmark', ticker, strategyId);
    const params = new URLSearchParams({ ticker: encodedTicker, strategy_id: strategyId });

    async function fetchBenchmark() {
      try {
        const response = await fetch(`${API_BASE}/benchmark?${params.toString()}`);

        if (!response.ok) {
          let message = `Server returned ${response.status}`;
          try {
            const body = await response.json();
            message = body.error ?? message;
          } catch (_) { /* body wasn't JSON */ }
          throw new Error(message);
        }

        const json = await response.json();
        if (cancelled) return;

        // If the server signals a schema change, wipe the stale cache entry
        if (json.full_refresh) {
          clearCache(currentKey);
        }

        setData(json);

        // Only cache non-empty, data-bearing responses
        if (!json.no_data) {
          writeCache(currentKey, json);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err.message);
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    fetchBenchmark();

    return () => { cancelled = true; };
  }, [ticker, encodedTicker, strategyId]); // Re-fetch whenever ticker or strategy changes

  return { data, loading, error };
}
