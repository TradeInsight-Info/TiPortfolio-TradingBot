import { useState, useEffect } from "react";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '/api';

export function useConfig() {
  const [initialAmount, setInitialAmount] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;

    async function fetchConfig() {
      try {
        const response = await fetch(`${API_BASE}/config`);
        const json = await response.json();

        if (!response.ok) {
          throw new Error(json.error ?? `Server returned ${response.status}`);
        }

        if (!cancelled) {
          setInitialAmount(json.initial_amount !== null ? Number(json.initial_amount) : null);
        }
      } catch (err) {
        if (!cancelled) setError(err.message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    fetchConfig();
    return () => { cancelled = true; };
  }, []);

  return { initialAmount, loading, error };
}
