import { UiError } from '../../i18n';
import { useCallback, useRef, useState } from 'react';
import { api } from '../../api';
import { ApiError } from '../../api/errors';
import type { CorrectionDocument, EditableFields } from '../../api/correctionTypes';
import { useResource } from '../../hooks/useResource';
import { correctionDraft, draftFields } from './correctionDraft';
import type { CorrectionDraft } from './correctionDraft';
import type { ActivityColumn, Compound } from '../../api/types';

export function useCorrection(
  projectId: string,
  compound: Compound,
  columns: ActivityColumn[],
  onSaved: () => void,
) {
  const compoundId = compound.id;
  const load = useCallback(
    (signal: AbortSignal) => api.getCorrection(projectId, compoundId, signal),
    [projectId, compoundId],
  );
  const resource = useResource(`correction:${projectId}:${compoundId}`, load);
  const [basis, setDocument] = useState<CorrectionDocument | null>(null);
  const [editedDraft, setDraft] = useState<CorrectionDraft | null>(null);
  const document = basis ?? resource.data;
  const draft =
    editedDraft ?? (document ? correctionDraft(document.values, compound, columns) : null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [blocked, setBlocked] = useState(false);
  const [message, setMessage] = useState('');
  const uncertain = useRef<{ basis: CorrectionDocument; fields: EditableFields } | null>(null);
  async function save() {
    if (!document || !draft || busy || blocked) return;
    setBusy(true);
    setError(null);
    setMessage('');
    try {
      const fields = draftFields(draft);
      uncertain.current = { basis: document, fields };
      await api.saveCorrection(projectId, compoundId, document, fields);
      uncertain.current = null;
      onSaved();
    } catch (failure) {
      setError(failure instanceof Error ? failure : new UiError('修正保存失败。'));
      if (failure instanceof ApiError && (failure.status === 409 || failure.uncertain)) {
        setBlocked(true);
        if (!failure.uncertain) uncertain.current = null;
      } else uncertain.current = null;
    } finally {
      setBusy(false);
    }
  }
  async function readLatest() {
    setBusy(true);
    setError(null);
    try {
      const latest = await load(new AbortController().signal);
      const pending = uncertain.current;
      if (
        pending &&
        latest.source_fingerprint === pending.basis.source_fingerprint &&
        latest.revision > pending.basis.revision &&
        JSON.stringify(latest.values) === JSON.stringify(pending.fields)
      ) {
        uncertain.current = null;
        onSaved();
        return;
      }
      uncertain.current = null;
      if (draft) setDraft(draft);
      setDocument(latest);
      setBlocked(false);
      setMessage('已读取保存版本，草稿保留。请确认后再保存。');
    } catch (failure) {
      setError(failure instanceof Error ? failure : new UiError('当前版本加载失败。'));
    } finally {
      setBusy(false);
    }
  }
  return { resource, document, draft, setDraft, busy, blocked, error, message, save, readLatest };
}
