import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../../api';
import type { HistoryAction, HistoryEntry, HistoryTarget } from '../../api/historyTypes';
import { useResource } from '../../hooks/useResource';

export function useHistoryMutation(
  target: HistoryTarget,
  action: HistoryAction,
  onChanged: (entry: HistoryEntry) => void,
) {
  const { kind, id } = target;
  const load = useCallback((signal: AbortSignal) => api.historyEntry(kind, id, signal), [kind, id]);
  const resource = useResource(`history-preview:${kind}:${id}`, load);
  const [current, setCurrent] = useState<HistoryEntry | null>(null);
  const [checking, setChecking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<Error | null>(null);
  const [needsRefresh, setNeedsRefresh] = useState(false);
  const mounted = useRef(false);
  const inFlight = useRef(false);
  const reader = useRef<AbortController | null>(null);
  const changed = useRef(onChanged);
  useEffect(() => {
    changed.current = onChanged;
  }, [onChanged]);
  async function refresh() {
    if (inFlight.current) return;
    reader.current?.abort();
    const controller = new AbortController();
    reader.current = controller;
    setChecking(true);
    setFailure(null);
    try {
      const refreshed = await api.historyEntry(kind, id, controller.signal);
      if (!mounted.current || controller.signal.aborted) return;
      setCurrent(refreshed);
      setNeedsRefresh(false);
      if (entry && entry.deleted_at !== refreshed.deleted_at) changed.current(refreshed);
    } catch (reason) {
      if (!mounted.current || controller.signal.aborted) return;
      setNeedsRefresh(true);
      setFailure(reason instanceof Error ? reason : new Error('无法核对记录状态。'));
    } finally {
      if (mounted.current && !controller.signal.aborted) setChecking(false);
    }
  }
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      reader.current?.abort();
    };
  }, []);
  const entry = current ?? resource.data;
  const loading = checking || resource.loading;
  const error = failure ?? (current === null ? resource.error : null);
  const completed =
    entry !== null && (action === 'delete' ? entry.deleted_at !== null : entry.deleted_at === null);
  const allowed = entry !== null && (action === 'delete' ? entry.can_delete : entry.can_restore);
  const canConfirm = allowed && !completed && !loading && !busy && !needsRefresh && !error;
  async function confirm() {
    if (!entry || !canConfirm || inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setFailure(null);
    try {
      const result =
        action === 'delete'
          ? await api.deleteHistory(kind, id, entry.revision)
          : await api.restoreHistory(kind, id, entry.revision);
      if (!mounted.current) return;
      setCurrent(result);
      changed.current(result);
    } catch (reason) {
      if (!mounted.current) return;
      // Even a conflict/server error requires a new authoritative GET. Never replay a write.
      setNeedsRefresh(true);
      setFailure(
        reason instanceof Error ? reason : new Error('操作结果无法确认，请先刷新核对状态。'),
      );
    } finally {
      inFlight.current = false;
      if (mounted.current) setBusy(false);
    }
  }
  return {
    entry,
    loading,
    busy,
    error,
    needsRefresh,
    completed,
    canConfirm,
    confirm,
    refresh: () => void refresh(),
  };
}
