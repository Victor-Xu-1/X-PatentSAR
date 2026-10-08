import { useLayoutEffect, useRef } from 'react';

/** Capture at dispatch, not completion. Leaving and returning never revives an old owner. */
export function useSARScope(context: string, active: boolean) {
  const current = useRef<{ active: boolean } | null>(null);
  useLayoutEffect(() => {
    const owner = { active };
    current.current = owner;
    return () => {
      owner.active = false;
    };
  }, [context, active]);
  return () => {
    const owner = current.current;
    return () => Boolean(owner?.active && current.current === owner);
  };
}
