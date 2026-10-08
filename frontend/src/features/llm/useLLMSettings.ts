import { UiError } from '../../i18n';
import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError } from '../../api/errors';
import { llmApi } from '../../api/llmApi';
import type { LLMApi } from '../../api/llmApi';
import type { LLMSettings } from '../../api/llmTypes';
import { dirtyLLMDraft, llmDraft, llmSaveRequest, updateLLMDraft } from './llmDraft';
import type { LLMDraft } from './llmDraft';
import { llmRequestError } from './llmMessages';

interface SettingsState {
  settings: LLMSettings | null;
  base: LLMSettings | null;
  draft: LLMDraft | null;
  open: boolean;
  loading: boolean;
  busy: boolean;
  readError: Error | null;
  error: Error | null;
  needsRefresh: boolean;
  saved: boolean;
}

export function useLLMSettings(api: LLMApi = llmApi) {
  const [state, setState] = useState<SettingsState>({
    settings: null,
    base: null,
    draft: null,
    open: false,
    loading: true,
    busy: false,
    readError: null,
    error: null,
    needsRefresh: false,
    saved: false,
  });
  const alive = useRef(true);
  const writing = useRef(false);
  const readController = useRef<AbortController | null>(null);
  const refresh = useCallback(async () => {
    if (writing.current) return;
    readController.current?.abort();
    const controller = new AbortController();
    readController.current = controller;
    setState((current) => ({ ...current, loading: true, readError: null }));
    try {
      const settings = await api.settings(controller.signal);
      if (!alive.current || controller.signal.aborted) return;
      setState((current) => {
        const preserve = Boolean(
          current.open &&
          current.draft &&
          current.base &&
          dirtyLLMDraft(current.draft, current.base),
        );
        return {
          ...current,
          settings,
          base: preserve ? current.base : settings,
          draft: preserve && current.draft ? { ...current.draft, apiKey: '' } : llmDraft(settings),
          loading: false,
          readError: null,
          error: null,
          needsRefresh: false,
          saved: false,
        };
      });
    } catch (error) {
      if (alive.current && !controller.signal.aborted)
        setState((current) => ({ ...current, loading: false, readError: llmRequestError(error) }));
    }
  }, [api]);

  useEffect(() => {
    alive.current = true;
    void refresh();
    return () => {
      alive.current = false;
      readController.current?.abort();
      // A dispatched write is not cancelled/replayed by navigation. The next
      // panel mount must read the server before it can submit another write.
    };
  }, [refresh]);

  const dirty = Boolean(state.draft && state.base && dirtyLLMDraft(state.draft, state.base));
  const conflict = Boolean(
    state.base && state.settings && state.base.revision !== state.settings.revision,
  );
  const unavailable = state.loading || state.readError !== null || state.needsRefresh || conflict;
  function open() {
    if (!state.settings || unavailable || writing.current) return;
    setState((current) => ({
      ...current,
      open: true,
      base: current.settings,
      draft: llmDraft(current.settings!),
      error: null,
      saved: false,
    }));
  }
  function close() {
    if (writing.current) return;
    setState((current) => ({
      ...current,
      open: false,
      draft: null,
      base: null,
      error: null,
      saved: false,
    }));
  }
  function update(update: Partial<LLMDraft>) {
    if (writing.current || state.loading || !state.settings?.editable) return;
    setState((current) => ({
      ...current,
      draft: current.draft ? updateLLMDraft(current.draft, update) : null,
      error: null,
      saved: false,
    }));
  }
  function acceptRevision() {
    if (unavailable && (state.loading || state.readError || state.needsRefresh)) return;
    if (writing.current) return;
    setState((current) => ({ ...current, base: current.settings, error: null, saved: false }));
  }
  function failedWrite(error: unknown) {
    if (!alive.current) return;
    const needsRefresh =
      !(error instanceof ApiError) ||
      error.uncertain ||
      error.status === 409 ||
      error.status >= 500;
    setState((current) => ({
      ...current,
      error: llmRequestError(error, true),
      needsRefresh,
      draft: current.draft ? { ...current.draft, apiKey: '' } : null,
    }));
  }
  async function save() {
    if (
      !state.base ||
      !state.draft ||
      !state.settings?.editable ||
      unavailable ||
      writing.current ||
      !dirty
    )
      return;
    let request;
    try {
      request = llmSaveRequest(state.draft, state.base);
    } catch (error) {
      setState((current) => ({
        ...current,
        error: error instanceof Error ? error : new UiError('配置无效。'),
      }));
      return;
    }
    writing.current = true;
    setState((current) => ({ ...current, busy: true, error: null, saved: false }));
    try {
      const settings = await api.save(request);
      if (alive.current)
        setState((current) => ({
          ...current,
          settings,
          base: settings,
          draft: llmDraft(settings),
          saved: true,
        }));
    } catch (error) {
      failedWrite(error);
    } finally {
      writing.current = false;
      if (alive.current) setState((current) => ({ ...current, busy: false }));
    }
  }
  const canTest = Boolean(
    state.settings?.status === 'ready' && !dirty && !unavailable && !state.busy,
  );
  async function test() {
    if (!state.settings || !canTest || writing.current) return;
    writing.current = true;
    setState((current) => ({ ...current, busy: true, error: null }));
    try {
      const result = await api.test(state.settings.revision, state.settings.limits.timeout_seconds);
      if (alive.current)
        setState((current) => ({
          ...current,
          settings: current.settings ? { ...current.settings, last_test: result } : null,
        }));
    } catch (error) {
      failedWrite(error);
    } finally {
      writing.current = false;
      if (alive.current) setState((current) => ({ ...current, busy: false }));
    }
  }
  return {
    ...state,
    dirty,
    conflict,
    unavailable,
    canTest,
    openDialog: open,
    close,
    update,
    refresh,
    acceptRevision,
    save,
    test,
  };
}

export type LLMSettingsController = ReturnType<typeof useLLMSettings>;
