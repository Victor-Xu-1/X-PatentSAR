import { useCallback, useEffect, useState } from 'react';

interface State<T> {
  key: string;
  data: T | null;
  error: Error | null;
  loading: boolean;
}
export interface Resource<T> {
  data: T | null;
  error: Error | null;
  loading: boolean;
  reload: () => void;
}
export function useResource<T>(
  key: string | null,
  load: (signal: AbortSignal) => Promise<T>,
  poll?: { milliseconds: number; while: (value: T) => boolean },
): Resource<T> {
  const [revision, setRevision] = useState(0);
  const [state, setState] = useState<State<T>>({
    key: '',
    data: null,
    error: null,
    loading: false,
  });
  const reload = useCallback(() => setRevision((v) => v + 1), []);
  const interval = poll?.milliseconds;
  const shouldPoll = poll?.while;
  useEffect(() => {
    if (key === null) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const run = async () => {
      setState((old) => ({
        key,
        data: old.key === key ? old.data : null,
        error: null,
        loading: true,
      }));
      try {
        const data = await load(controller.signal);
        if (controller.signal.aborted) return;
        setState({ key, data, error: null, loading: false });
        if (interval && shouldPoll?.(data)) timer = setTimeout(() => void run(), interval);
      } catch (error) {
        if (!controller.signal.aborted)
          setState({
            key,
            data: null,
            error: error instanceof Error ? error : new Error('加载失败。'),
            loading: false,
          });
      }
    };
    void run();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [key, load, revision, interval, shouldPoll]);
  if (key === null) return { data: null, error: null, loading: false, reload };
  if (state.key !== key) return { data: null, error: null, loading: true, reload };
  return { data: state.data, error: state.error, loading: state.loading, reload };
}
