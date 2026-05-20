import { useState, useEffect, useCallback } from "react";
import { cacheKey, readCache, writeCache, clearCache } from '../utils/cache';

// In dev, Vite proxies /api → localhost:5000. In prod (Cloudflare Pages),
// VITE_API_BASE_URL points directly at the Flask host (no /api prefix on Flask).
const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '/api';
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
      // Detect stale cache: if the first cached event has no `id` field,
      // the cache was written by the old version of the API.
      // Force a full refresh so we get the new format with id + fill fields.
      const cacheIsStale =
        cached?.events?.length > 0 && cached.events[0].id == null;

      if (cacheIsStale) {
        clearCache(CACHE_KEY);
      }
      // Build the incremental URL: if we have cached data, ask for newer records
      const latestTimestamp = (!cacheIsStale && cached?.latestTimestamp) ? cached.latestTimestamp : null;
      const url = latestTimestamp
        ? `${API_BASE}/delta?since=${encodeURIComponent(latestTimestamp)}`
        : `${API_BASE}/delta`;

      try {
        const response = await fetch(url);

        // Read the body ONCE as JSON regardless of status
        const data = await response.json();

        // Treat non-2xx as an error
        if (!response.ok) {
          throw new Error(`Server returned ${response.status}`);
        }
        if (cancelled) return;

        // Server signals a schema change: wipe stale cache and use fresh data only
        if (data.full_refresh) {
          clearCache(CACHE_KEY);
          const freshEvents = data.events ?? [];
          setEvents(freshEvents);
          if (freshEvents.length > 0) {
            persistCache(freshEvents);
          }
          return;
        }

        const incoming = data.events ?? [];

        // When cache was stale, we did a full fetch (/delta with no ?since).
        // incoming already contains ALL events in the new format (with id + fill fields).
        // Do NOT merge with stale cache - mergeEvents deduplicates by timestamp,
        // which would discard all incoming events and keep the old id-less data.
        if (cacheIsStale) {
          setEvents(incoming);
          if (incoming.length > 0) {
            persistCache(incoming);
          }
          return;
        }
        
        // Merge: new records come first (newest-first order), sorted by timestamp
        const merged = mergeEvents(cached?.events ?? [], incoming);
        setEvents(merged);
        if (merged.length > 0) {
          persistCache(merged);
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
  }, []); // Run once on mount

  /**
   * Re-poll Alpaca fill status for a single event's pending orders.
   *
   * Called when the user clicks the retry button on a pending event.
   * Updates the matching event in local state (and cache) with the
   * freshest fill data returned by the server.
   *
   * @param {number} eventId - The event's numeric id from the API response.
   * @returns {{ ok: boolean, error?: string }}
   */
  const refreshEvent = useCallback(async (eventId) => {
    try {
      const response = await fetch(`${API_BASE}/delta/${eventId}/refresh`, {
        method: "POST",
      });
      const data = await response.json();

      if (!response.ok) {
        return { ok: false, error: data.error ?? `Server returned ${response.status}` };
      }

      // Swap the stale event in state with the updated one returned by the server
      setEvents(prev => {
        const updated = prev.map(e => (e.id === eventId ? data : e));
        persistCache(updated);
        return updated;
      });

      return { ok: true };
    } catch (err) {
      return { ok: false, error: err.message };
    }
  }, []);

  return { events, loading, error, refreshEvent };
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
