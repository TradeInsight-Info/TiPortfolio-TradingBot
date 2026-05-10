import { useState, useEffect } from "react";
import { cacheKey, readCache, writeCache, clearCache } from '../utils/cache';

const CACHE_KEY = cacheKey('delta');

export function useDelta() {  
  // Initialise from cache immediately so the UI renders without waiting for the network
  const cached = readCache(CACHE_KEY);
  const [events, setEvents] = useState(cached?.events ?? []);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;

    async function fetchDelta() {
      // Build the incremental URL: if we have cached data, ask for newer records
      const latestTimestamp = cached?.latestTimestamp ?? null;
      const url = latestTimestamp
        ? `/api/delta?since=${encodeURIComponent(latestTimestamp)}`
        : '/api/delta';
      
      try {
        // Vite proxy handles routing
        const response = await fetch(url);

        // Read the body ONCE as JSON regardless of status
        const data = await response.json();

        // Treat non-2xx as an error
        if (!response.ok) {
          throw new Error(`Server returned ${response.status}`);
        }
        if (cancelled) return;

        // If the server signals a schema change, wipe the cache and use fresh data only
        if (data.full_refresh) {
          clearCache(CACHE_KEY);
          const freshEvents = data.events ?? [];
          setEvents(freshEvents);
          persistCache(freshEvents);
          return;
        }

        const incoming = data.events ?? [];

        // Merge: new records come first (newest-first order), sorted by timestamp
        const merged = mergeEvents(cached?.events ?? [], incoming);
        setEvents(merged);
        persistCache(merged);

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

/**
 * Merge cached events with incoming events from the background fetch.
 * Incoming records (from ?since=...) are prepended; 
 * duplicates are removed by timestamp.
 * Final list remains sorted newest-first.
 */
function mergeEvents(cachedEvents, incomingEvents) {
  const seen = new Set(cachedEvents.map((e) => e.timestamp));
  const truly_new = incomingEvents.filter((e) => !seen.has(e.timestamp));
  
  // Explicitly sort newest-first, regardless of input order
  return [...truly_new, ...cachedEvents].sort((a, b) =>
    new Date(b.timestamp) - new Date(a.timestamp)
  );
}

/**
 * Retrieves the latest timestamp from the merged list and persist to localStorage.
 * The latest timestamp is the first element's timestamp (newest-first order).
 */
function persistCache(events) {
  const latestTimestamp = events.length > 0 ? events[0].timestamp : null;
  writeCache(CACHE_KEY, { events, latestTimestamp });
}
