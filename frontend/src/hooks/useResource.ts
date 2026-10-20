import { useCallback, useEffect, useState } from 'react';
import { readRecoveryDelay } from '../api/readRecovery';

interface State<T> {
  key: string;
  data: T | null;
  error: Error | null;
  loading: boolean;
  readConfirmed: boolean;
}
export interface Resource<T> {
  data: T | null;
  error: Error | null;
  loading: boolean;
  reload: () => void;
  /** Same-key successful read retained during ordinary polling, not action authority. */
  readConfirmed?: boolean;
}
export interface ResourceOptions {
  retainOnError?: boolean;
  /** Explicit opt-in for audited GET callbacks, never mutations or readonly POST. */
  recoverGetErrors?: boolean;
}
export function useResource<T>(
  key: string | null,
  load: (signal: AbortSignal) => Promise<T>,
  poll?: { milliseconds: number; while: (value: T) => boolean },
  options: ResourceOptions = {},
): Resource<T> {
  const [revision, setRevision] = useState(0);
  const [state, setState] = useState<State<T>>({
    key: '',
    data: null,
    error: null,
    loading: false,
    readConfirmed: false,
  });
  const reload = useCallback(() => setRevision((v) => v + 1), []);
  const interval = poll?.milliseconds;
  const shouldPoll = poll?.while;
  const retainOnError = options.retainOnError === true;
  const recoverGetErrors = options.recoverGetErrors === true;
  useEffect(() => {
    if (key === null) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    let consecutiveFailures = 0;
    const run = async (background = false) => {
      const recovering = consecutiveFailures > 0;
      setState((old) => ({
        key,
        data: old.key === key ? old.data : null,
        error: recovering ? old.error : null,
        loading: true,
        readConfirmed: background && old.key === key && old.readConfirmed,
      }));
      try {
        const data = await load(controller.signal);
        if (controller.signal.aborted) return;
        consecutiveFailures = 0;
        setState({ key, data, error: null, loading: false, readConfirmed: true });
        if (interval && shouldPoll?.(data)) timer = setTimeout(() => void run(true), interval);
      } catch (error) {
        if (controller.signal.aborted) return;
        consecutiveFailures += 1;
        setState((old) => ({
          key,
          data: retainOnError && old.key === key ? old.data : null,
          error: error instanceof Error ? error : new Error('加载失败。'),
          loading: false,
          readConfirmed: false,
        }));
        const delay = recoverGetErrors ? readRecoveryDelay(error, consecutiveFailures) : null;
        if (delay !== null) timer = setTimeout(() => void run(true), delay);
      }
    };
    void run();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [key, load, revision, interval, shouldPoll, retainOnError, recoverGetErrors]);
  if (key === null)
    return { data: null, error: null, loading: false, readConfirmed: false, reload };
  if (state.key !== key)
    return { data: null, error: null, loading: true, readConfirmed: false, reload };
  return {
    data: state.data,
    error: state.error,
    loading: state.loading,
    readConfirmed: state.readConfirmed,
    reload,
  };
}
