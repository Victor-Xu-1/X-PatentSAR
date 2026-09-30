import { useState } from 'react';
import { api } from '../../api';
import { ApiError } from '../../api/errors';
import type { Compound, ReviewDecision } from '../../api/types';
import { Dialog } from '../../components/Dialog';
import { ErrorNotice } from '../../components/Feedback';
import { dateText, reviewLabels } from '../../model/presentation';

export function ReviewDialog({
  projectId,
  compound,
  onClose,
  onSaved,
}: {
  projectId: string;
  compound: Compound;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [decision, setDecision] = useState<ReviewDecision>(
    compound.review?.decision ?? 'needs_review',
  );
  const [note, setNote] = useState(compound.review?.note ?? '');
  const [revision, setRevision] = useState(compound.review?.revision ?? 0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [conflict, setConflict] = useState(false);
  const [latest, setLatest] = useState<Compound['review']>(null);
  const [message, setMessage] = useState('');
  async function submit() {
    setBusy(true);
    setError(null);
    setMessage('');
    try {
      await api.review(projectId, compound.id, decision, note.trim(), revision);
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e : new Error('复核保存失败。'));
      if (e instanceof ApiError && e.status === 409) setConflict(true);
    } finally {
      setBusy(false);
    }
  }
  async function reloadRevision() {
    setBusy(true);
    setError(null);
    try {
      const results = await api.results(
        projectId,
        { q: compound.display_id, confidence: '', review: '', target: '', page: 1, page_size: 100 },
        new AbortController().signal,
      );
      const current = results.items.find((row) => row.id === compound.id);
      if (!current) throw new Error('未找到当前化合物。请关闭对话框并刷新结果后重试。');
      setLatest(current.review);
      setRevision(current.review?.revision ?? 0);
      setConflict(false);
      setMessage('已载入最新版本。您的草稿已保留，请比较最新注记并确认后再保存。');
    } catch (e) {
      setError(e instanceof Error ? e : new Error('最新版本加载失败。'));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog title={`人工复核 · ${compound.display_id}`} onClose={onClose} busy={busy}>
      <form
        className="dialog-body"
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <div className="info-banner">
          复核仅保存人工注记，不修改结构、SMILES、提取产物或核心 QA 验收。
        </div>
        <p className="muted">
          预期版本 {revision} · 上次更新 {dateText(compound.review?.updated_at ?? null)}
        </p>
        <label className="form-field">
          复核决定
          <select
            data-initial-focus
            value={decision}
            disabled={busy}
            onChange={(e) => setDecision(e.target.value as ReviewDecision)}
          >
            {Object.entries(reviewLabels).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label className="form-field">
          复核注记
          <textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            rows={5}
            maxLength={4000}
            disabled={busy}
            placeholder="记录证据、疑点或人工确认理由"
          />
        </label>
        {latest && (
          <div className="revision-comparison">
            <strong>最新已保存注记 · 版本 {latest.revision}</strong>
            <p>{reviewLabels[latest.decision]}</p>
            <pre>{latest.note || '无注记'}</pre>
          </div>
        )}
        {message && <output className="info-banner">{message}</output>}
        {error && <ErrorNotice error={error} />}
        {conflict && (
          <div className="conflict">
            <p>此记录已被更新，未覆盖他人的复核。</p>
            <button type="button" onClick={() => void reloadRevision()} disabled={busy}>
              载入最新版本并保留草稿
            </button>
          </div>
        )}
        <footer className="dialog-actions">
          <button type="button" onClick={onClose} disabled={busy}>
            取消
          </button>
          <button type="submit" className="primary" disabled={busy || conflict}>
            {busy ? '正在保存…' : '保存复核注记'}
          </button>
        </footer>
      </form>
    </Dialog>
  );
}
