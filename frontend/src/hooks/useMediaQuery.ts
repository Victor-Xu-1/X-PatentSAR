import { useCallback, useMemo, useSyncExternalStore } from 'react';
export function useMediaQuery(query: string): boolean {
  const media = useMemo(
    () => (typeof window.matchMedia === 'function' ? window.matchMedia(query) : null),
    [query],
  );
  const subscribe = useCallback(
    (callback: () => void) => {
      media?.addEventListener('change', callback);
      return () => media?.removeEventListener('change', callback);
    },
    [media],
  );
  return useSyncExternalStore(
    subscribe,
    () => media?.matches ?? false,
    () => false,
  );
}
