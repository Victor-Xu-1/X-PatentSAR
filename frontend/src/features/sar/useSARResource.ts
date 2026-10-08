import { useCallback, useState } from 'react';
import { useResource } from '../../hooks/useResource';
import type { Resource } from '../../hooks/useResource';

export interface SARResource<T> extends Resource<T> {
  /** Cached data may keep a draft mounted, but cannot authorize an action. */
  validated: boolean;
}

/** Retains one identity's last DTO, delegating reads, aborts and polling to the shared hook. */
export function useSARResource<T>(
  identity: string,
  active: boolean,
  load: (signal: AbortSignal) => Promise<T>,
  poll?: { milliseconds: number; while: (value: T) => boolean },
): SARResource<T> {
  const [cycle, setCycle] = useState({ identity, active, generation: 0 });
  const changed = cycle.identity !== identity || cycle.active !== active;
  const generation = cycle.generation + (changed ? 1 : 0);
  // Adjust before committing a changed identity/activation, so the very first
  // returning render cannot enable actions with the previous read's success.
  if (changed) setCycle({ identity, active, generation });
  const [snapshot, setSnapshot] = useState<{ identity: string; data: T } | null>(null);
  const retain = useCallback(
    async (signal: AbortSignal) => {
      const data = await load(signal);
      if (!signal.aborted) setSnapshot({ identity, data });
      return data;
    },
    [identity, load],
  );
  const resource = useResource(
    active ? JSON.stringify([identity, generation]) : null,
    retain,
    poll,
  );
  const reload = useCallback(() => {
    setCycle((old) => ({ ...old, generation: old.generation + 1 }));
  }, []);
  return {
    ...resource,
    data: resource.data ?? (snapshot?.identity === identity ? snapshot.data : null),
    validated: active && resource.data !== null && !resource.loading && !resource.error,
    reload,
  };
}
