import { useState, useEffect, useCallback } from "react";

const SUPPORTED_TICKERS = ["SPY", "QQQ", "QQQ+GLD+BIL"];

export function useBenchmark(ticker) {
  const [data, setData]       = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState(null);

  // Encode '+' in composite ticker for URL query string
  const encodedTicker = encodeURIComponent(ticker);

  const fetchBenchmark = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const response = await fetch(`/api/benchmark?ticker=${encodedTicker}`);
      const json = await response.json();

      if (!response.ok) {
        // Server returned 4xx/5xx; use the error message from the body
        throw new Error(json.error ?? `Server returned ${response.status}`);
      }

      setData(json);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [encodedTicker]);

  useEffect(() => {
    fetchBenchmark();
  }, [fetchBenchmark]); // Re-fetch whenever ticker changes

  return { data, loading, error };
}