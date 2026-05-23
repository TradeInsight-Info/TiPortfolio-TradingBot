import { useState, useEffect } from "react";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "/api";

export function usePositions() {
  const [data, setData]       = useState(null);   // {positions, equity, cash, as_of, stale?}
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState(null);

  useEffect(() => {
    let cancelled = false;

    async function fetchPositions() {
      try {
        const resp = await fetch(`${API_BASE}/positions`);
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
  }, []);

  return { data, loading, error };
}
