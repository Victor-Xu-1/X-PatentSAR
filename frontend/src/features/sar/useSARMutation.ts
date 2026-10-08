import { useEffect, useRef, useState } from 'react';
import { ApiError } from '../../api/errors';
import { UncertainSARWrite } from '../../api/sarMutation';
import { UiError } from '../../i18n';
import { useSARScope } from './useSARScope';

export function useSARMutation({
  scope = '',
  active = true,
}: { scope?: string; active?: boolean } = {}) {
  const capture = useSARScope(scope, active);
  const mounted = useRef(true);
  const running = useRef(false);
  const retry = useRef<(() => Promise<void>) | null>(null);
  const [state, setState] = useState<{
    busy: boolean;
    error: Error | null;
    uncertain: boolean;
    requestId: string | null;
    success: boolean;
  }>({
    busy: false,
    error: null,
    uncertain: false,
    requestId: null,
    success: false,
  });
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  async function run<T>(
    action: () => Promise<T>,
    onSuccess: (value: T) => void,
    requestId: string | null = null,
    ownsCompletion = capture(),
  ) {
    if (running.current) return;
    running.current = true;
    setState({ busy: true, error: null, uncertain: false, requestId, success: false });
    try {
      const result = await action();
      retry.current = null;
      if (mounted.current) {
        setState({ busy: false, error: null, uncertain: false, requestId: null, success: true });
        if (ownsCompletion()) onSuccess(result);
      }
    } catch (error) {
      const failure = error instanceof Error ? error : new UiError('SAR 操作失败。');
      const uncertain = failure instanceof ApiError && failure.uncertain;
      const retainedId = failure instanceof UncertainSARWrite ? failure.requestId : requestId;
      // Explicit retry only: keep the exact captured payload and request ID, never regenerate it.
      retry.current =
        uncertain && retainedId ? () => run(action, onSuccess, retainedId, ownsCompletion) : null;
      if (mounted.current)
        setState({ busy: false, error: failure, uncertain, requestId: retainedId, success: false });
    } finally {
      running.current = false;
    }
  }
  return {
    ...state,
    locked: state.busy || state.uncertain,
    run,
    canRetry: state.uncertain && state.requestId !== null,
    clearError: () =>
      setState((old) =>
        old.busy || old.uncertain ? old : { ...old, error: null, success: false },
      ),
    retry: () => {
      if (retry.current) void retry.current();
    },
  };
}
