// Prefix to avoid collisions with other localStorage keys
const KEY_PREFIX = 'tradeinsight_';

/**
 * Build the localStorage key for a given view and optional ticker.
 * Examples:
 *   cacheKey('delta')          -> 'tradeinsight_delta'
 *   cacheKey('benchmark','SPY') -> 'tradeinsight_benchmark_SPY'
 */
export function cacheKey(view, ticker = '') {
  return ticker ? `${KEY_PREFIX}${view}_${ticker}` : `${KEY_PREFIX}${view}`;
}

/**
 * Read and parse a JSON value from localStorage.
 * Returns null if the key does not exist or the stored value cannot be parsed.
 * Never throws - quota or parse errors are swallowed silently.
 */
export function readCache(key) {
  try {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : null;
  } catch {
    // Silently ignore JSON parse errors or SecurityError in sandboxed iframes
    return null;
  }
}

/**
 * Serialise value to JSON and write it to localStorage under key.
 * Silently falls back to no-op when the quota is exceeded or storage is
 * unavailable (e.g. private browsing in some browsers).
 */
export function writeCache(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
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