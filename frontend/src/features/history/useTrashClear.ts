import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../../api';
import { ApiError } from '../../api/errors';
import type { TrashPlan, TrashClearRequest, TrashClearReceipt } from '../../api/historyTrashTypes';
import { useResource } from '../../hooks/useResource';
import { UiError } from '../../i18n';
import { historyKinds } from '../../api/historyTypes';

export function useTrashClear(onDone: () => void) {
  const load = useCallback((signal: AbortSignal) => api.trashPlan(signal), []);
  const resource = useResource('history:trash-clear-plan', load);
  const [plan, setPlan] = useState<TrashPlan | null>(null);
  const [submittedReceipt, setReceipt] = useState<TrashClearReceipt | null>(null);
  const [request, setRequest] = useState<TrashClearRequest | null>(null);
  const [busy, setBusy] = useState(false),
    [checking, setChecking] = useState(false);
  const [failure, setFailure] = useState<Error | null>(null),
    [needsCheck, setNeedsCheck] = useState(false);
  const mounted = useRef(false),
    inFlight = useRef(false),
    reader = useRef<AbortController | null>(null);
  const done = useRef(onDone);
  const expectedCounts = useRef<TrashPlan['counts'] | null>(null);
  const expectedFiles = useRef<number | null>(null);
  useEffect(() => {
    done.current = onDone;
  }, [onDone]);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      reader.current?.abort();
    };
  }, []);
  const current = plan ?? resource.data;
  const receipt = submittedReceipt ?? current?.pending ?? null;
  const activeRequest =
    request ??
    (receipt?.status === 'cleanup_pending'
      ? {
          request_id: receipt.request_id,
          expected_revision: receipt.plan_revision,
          expected_total: receipt.cleared,
        }
      : null);
  const loading = resource.loading || checking;
  const error = failure ?? (plan === null ? resource.error : null);
  const canConfirm = Boolean(
    current &&
    (receipt?.status === 'cleanup_pending' || (current.total && !current.blocked && !receipt)) &&
    !loading &&
    !busy &&
    !needsCheck &&
    !error,
  );
  async function confirm() {
    if (!canConfirm || !current || inFlight.current) return;
    const submitted = activeRequest ?? {
      request_id: crypto.randomUUID().replaceAll('-', ''),
      expected_revision: current.revision,
      expected_total: current.total,
    };
    expectedCounts.current ??= receipt?.counts ?? current.counts;
    expectedFiles.current ??= receipt?.files_total ?? current.files_total;
    inFlight.current = true;
    setRequest(submitted);
    setBusy(true);
    setFailure(null);
    try {
      const result = await api.clearTrash(submitted);
      if (!mounted.current) return;
      if (
        result.files_total !== expectedFiles.current ||
        historyKinds.some((kind) => result.counts[kind] !== expectedCounts.current?.[kind])
      )
        throw new UiError('清空回执不匹配，未重复提交。');
      setReceipt(result);
      done.current();
    } catch (error) {
      if (mounted.current) {
        setNeedsCheck(true);
        setFailure(error instanceof Error ? error : new UiError('清空结果尚未确认。'));
      }
    } finally {
      inFlight.current = false;
      if (mounted.current) setBusy(false);
    }
  }
  async function check() {
    if (inFlight.current) return;
    reader.current?.abort();
    const controller = new AbortController();
    reader.current = controller;
    setChecking(true);
    setFailure(null);
    try {
      if (activeRequest) {
        try {
          const result = await api.trashClearReceipt(activeRequest.request_id, controller.signal);
          if (!mounted.current || controller.signal.aborted) return;
          if (
            result.plan_revision !== activeRequest.expected_revision ||
            result.cleared !== activeRequest.expected_total ||
            result.files_total !== (expectedFiles.current ?? receipt?.files_total) ||
            historyKinds.some(
              (kind) => result.counts[kind] !== (expectedCounts.current ?? receipt?.counts)?.[kind],
            )
          )
            throw new UiError('清空回执不匹配，未重复提交。');
          setReceipt(result);
          setNeedsCheck(false);
          done.current();
          return;
        } catch (error) {
          if (!(error instanceof ApiError) || error.status !== 404) throw error;
        }
      }
      const fresh = await api.trashPlan(controller.signal);
      if (!mounted.current || controller.signal.aborted) return;
      setPlan(fresh);
      if (
        activeRequest &&
        (fresh.revision !== activeRequest.expected_revision ||
          fresh.total !== activeRequest.expected_total)
      ) {
        setNeedsCheck(true);
        setFailure(new UiError('回收站已变化。请关闭后重新核对；未重复清空。'));
      } else {
        setNeedsCheck(false);
      }
    } catch (error) {
      if (mounted.current && !controller.signal.aborted) {
        setNeedsCheck(true);
        setFailure(error instanceof Error ? error : new UiError('清空结果尚未确认。'));
      }
    } finally {
      if (mounted.current && !controller.signal.aborted) setChecking(false);
    }
  }
  return {
    plan: current,
    receipt,
    busy,
    loading,
    error,
    needsCheck,
    canConfirm,
    confirm,
    check: () => void check(),
    retrying: request !== null && !needsCheck,
  };
}
