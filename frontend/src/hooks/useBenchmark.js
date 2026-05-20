import { useState, useEffect, useCallback } from "react";
import { cacheKey, readCache, writeCache, clearCache } from '../utils/cache';

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '/api';

export function useBenchmark(ticker) {
  const key = cacheKey('benchmark', ticker);

  // Initialise from cache so the chart renders immediately on repeat visits
  const cached = readCache(key);
  const [data, setData]       = useState(cached ?? null);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState(null);

  // Encode '+' in composite ticker for URL query string
  const encodedTicker = encodeURIComponent(ticker);

  const fetchBenchmark = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const response = await fetch(`${API_BASE}/benchmark?ticker=${encodedTicker}`);

      if (!response.ok) {
        let message = `Server returned ${response.status}`;
        try {
          const body = await response.json();
          message = body.error ?? message;
        } catch (_) { /* body wasn't JSON */ }
        throw new Error(message);
      }

      const json = await response.json();

      // If the server signals a schema change, wipe the stale cache entry
      if (json.full_refresh) {
        clearCache(key);
      }

      setData(json);
      
      // Only cache non-empty, data-bearing responses
      if (!json.no_data) {
        writeCache(key, json);
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [encodedTicker, key]);

  useEffect(() => {
    fetchBenchmark();
  }, [fetchBenchmark]); // Re-fetch whenever ticker changes

  return { data, loading, error };
}