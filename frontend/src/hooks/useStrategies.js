import { useState, useEffect } from "react";
const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "/api";

export function useStrategies() {
  const [strategies, setStrategies] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  useEffect(() => {
    fetch(`${API_BASE}/strategies`)
      .then((r) => {
        if (!r.ok) throw new Error(`Server returned ${r.status}`);
        return r.json();
      })
      .then((d) => setStrategies(Array.isArray(d) ? d : []))
      .catch((err) => { setStrategies([]); setError(err.message); })
      .finally(() => setLoading(false));
  }, []);
  return { strategies, loading, error };
}
