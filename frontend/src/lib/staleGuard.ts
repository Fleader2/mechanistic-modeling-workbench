/** Tracks the most recently started async request's key, so a response that
 * resolves out of order (a fast row click followed by a second, faster-
 * resolving one) can be detected as stale and ignored instead of
 * overwriting the newer selection's detail with an older one's. */
export function createStaleGuard<Key>() {
  let current: Key | null = null;
  return {
    start(key: Key): void {
      current = key;
    },
    isCurrent(key: Key): boolean {
      return current === key;
    },
  };
}
