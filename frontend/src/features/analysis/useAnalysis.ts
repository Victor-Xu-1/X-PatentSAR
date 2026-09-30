import { useEffect, useRef, useState } from 'react';
import { ApiError } from '../../api/errors';

export function useAnalysis<T>(onBusy?: (busy: boolean) => void) {
  const [result, setResult] = useState<T | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [uncertain, setUncertain] = useState(false);
  const [remainingSeconds, setRemaining] = useState<number | null>(null);
  const controller = useRef<AbortController | null>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  const blocked = useRef(false);
  function clearTimer() {
    if (timer.current) clearInterval(timer.current);
    timer.current = null;
  }
  useEffect(
    () => () => {
      controller.current?.abort();
      if (timer.current) clearInterval(timer.current);
    },
    [],
  );
  async function run(operation: (signal: AbortSignal) => Promise<T>) {
    if (controller.current || blocked.current) return;
    const active = new AbortController();
    controller.current = active;
    setBusy(true);
    setResult(null);
    setError(null);
    onBusy?.(true);
    const deadline = Date.now() + 190_000;
    setRemaining(190);
    timer.current = setInterval(() => {
      const seconds = Math.max(0, Math.ceil((deadline - Date.now()) / 1000));
      setRemaining(seconds);
      if (seconds === 0) clearTimer();
    }, 1000);
    try {
      const value = await operation(active.signal);
      if (!active.signal.aborted) {
        setResult(value);
        clearTimer();
        setRemaining(null);
      }
    } catch (e) {
      if (!active.signal.aborted) {
        setError(e instanceof Error ? e : new Error('分析失败。'));
        const unknown = e instanceof ApiError && e.uncertain;
        setUncertain(unknown);
        blocked.current = unknown;
        if (!unknown) {
          clearTimer();
          setRemaining(null);
        }
      }
    } finally {
      if (!active.signal.aborted) {
        controller.current = null;
        setBusy(false);
        onBusy?.(false);
      }
    }
  }
  function acknowledge() {
    if (remainingSeconds !== 0) return;
    blocked.current = false;
    setUncertain(false);
    setError(null);
    setRemaining(null);
  }
  return { result, busy, error, uncertain, remainingSeconds, acknowledge, run };
}
