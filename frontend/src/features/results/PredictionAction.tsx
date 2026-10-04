import { useState } from 'react';
import { api } from '../../api';
import { ApiError } from '../../api/errors';
import { ErrorNotice } from '../../components/Feedback';

export function PredictionAction({
  projectId,
  disabled,
  onQueued,
}: {
  projectId: string;
  disabled: boolean;
  onQueued: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [message, setMessage] = useState('');
  async function submit() {
    setBusy(true);
    setError(null);
    try {
      await api.createJob(projectId, null, { include_admet: true, admet_only: true });
      setMessage('已提交结构与指标补齐任务；复用已有结果，不重新提取 PDF。');
      onQueued();
    } catch (failure) {
      setError(failure instanceof Error ? failure : new Error('结构与指标补齐任务提交失败。'));
      if (failure instanceof ApiError && failure.uncertain) setUncertain(true);
    } finally {
      setBusy(false);
    }
  }
  async function check() {
    setBusy(true);
    setError(null);
    try {
      const jobs = await api.jobs(projectId, new AbortController().signal);
      const active = jobs.items.some((job) => job.status === 'queued' || job.status === 'running');
      setMessage(
        active
          ? '此项目已有任务，请查看上方实际进度。'
          : '已读取任务状态，请先核对任务记录，再决定是否提交。',
      );
      setUncertain(false);
      onQueued();
    } catch (failure) {
      setError(failure instanceof Error ? failure : new Error('任务状态读取失败。'));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="prediction-action">
      <button type="button" disabled={disabled || busy || uncertain} onClick={() => void submit()}>
        补齐结构与指标
      </button>
      {uncertain && (
        <button type="button" disabled={busy} onClick={() => void check()}>
          检查已提交任务
        </button>
      )}
      {message && <output className="info-banner">{message}</output>}
      {error && <ErrorNotice error={error} />}
    </div>
  );
}
