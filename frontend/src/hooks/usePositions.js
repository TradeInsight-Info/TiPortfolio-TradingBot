import { useState, useEffect } from "react";
import { useStrategy } from "../context/StrategyContext";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "/api";

export function usePositions() {
  const { strategyId } = useStrategy();
  const [data, setData]       = useState(null);   // {positions, equity, cash, as_of, stale?}
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState(null);

  useEffect(() => {
    if (!strategyId) return;

    let cancelled = false;

    async function fetchPositions() {
      try {
        const params = new URLSearchParams({ strategy_id: strategyId });
        const resp = await fetch(`${API_BASE}/positions?${params.toString()}`);
        const json = await resp.json();
        if (!resp.ok) throw new Error(json.error ?? `HTTP ${resp.status}`);
        if (!cancelled) setData(json);
      } catch (err) {
        if (!cancelled) setError(err.message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    fetchPositions();
    return () => { cancelled = true; };
  }, [strategyId]);

  return { data, loading, error };
}
