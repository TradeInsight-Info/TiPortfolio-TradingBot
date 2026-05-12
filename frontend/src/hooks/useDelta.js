import { useState, useEffect } from "react";

export function useDelta() {
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;

    async function fetchDelta() {
      try {
        // Vite proxy handles routing
        const response = await fetch('/api/delta');

        // Read the body ONCE as JSON regardless of status
        const data = await response.json();

        // Treat non-2xx as an error
        if (!response.ok) {
          throw new Error(`Server returned ${response.status}`);
        }

        if (!cancelled) {
          // API returns { count, events: [...] }
          setEvents(data.events ?? []);
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

    fetchDelta();

    // Cleanup: if the component unloaded before fetch completes, ignore the result
    return () => {
      cancelled = true;
    };
  }, []); // Run once on load

  return { events, loading, error };
}
