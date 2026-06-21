// Prefix to avoid collisions with other localStorage keys
const KEY_PREFIX = 'tradeinsight_';

// Default TTL for cached data (24 hours)
const DEFAULT_TTL_MS = 24 * 60 * 60 * 1000;

/**
 * Build the localStorage key for a given view and optional qualifier parts.
 * Variadic: any number of parts after view are joined with '_', falsy parts filtered out.
 * Examples:
 *   cacheKey('delta')                    -> 'tradeinsight_delta'
 *   cacheKey('benchmark', 'SPY')         -> 'tradeinsight_benchmark_SPY'
 *   cacheKey('benchmark', 'SPY', 'vix')  -> 'tradeinsight_benchmark_SPY_vix'
 */
export function cacheKey(view, ...parts) {
  const segments = parts.filter(Boolean);
  return segments.length
    ? `${KEY_PREFIX}${view}_${segments.join('_')}`
    : `${KEY_PREFIX}${view}`;
}

/**
 * Read and parse a value from localStorage.
 * Returns null if the key does not exist, cannot be parsed, or has expired.
 * Expired entries are removed automatically.
 * Never throws - quota or parse errors are swallowed silently.
 */
export function readCache(key, ttlMs = DEFAULT_TTL_MS) {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    // Entries without cachedAt are from the old format — treat as expired
    if (!parsed?.cachedAt) {
      localStorage.removeItem(key);
      return null;
    }
    if (Date.now() - parsed.cachedAt > ttlMs) {
      localStorage.removeItem(key);
      return null;
    }
    return parsed.data;
  } catch {
    // Silently ignore JSON parse errors or SecurityError in sandboxed iframes
    return null;
  }
}

/**
 * Serialise value to JSON and write it to localStorage under key.
 * Wraps the value in a {cachedAt, data} envelope for TTL tracking.
 * Silently falls back to no-op when the quota is exceeded or storage is
 * unavailable (e.g. private browsing in some browsers).
 */
export function writeCache(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify({ cachedAt: Date.now(), data: value }));
  } catch {
    // QuotaExceededError or SecurityError - app continues without caching
  }
}

/**
 * Remove a single cache entry.
 * Used when the server signals that a full refresh is required.
 */
export function clearCache(key) {
  try {
    localStorage.removeItem(key);
  } catch {
    // Silently ignore
  }
}