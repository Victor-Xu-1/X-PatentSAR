import { useState } from 'react';
import { MoreHorizontal, Play, RotateCcw, Square } from 'lucide-react';
import { api } from '../../api';
import type { Job, Project } from '../../api/types';
import { activeJob, jobStatusLabels } from '../../model/presentation';
import { ErrorNotice } from '../../components/Feedback';
import { Dialog } from '../../components/Dialog';
import { JobRecord } from './JobRecord';

export function JobActions({
  project,
  job,
  ready,
  onChange,
  compact = false,
}: {
  project: Project | null;
  job: Job | null;
  ready: boolean;
  onChange: () => void;
  compact?: boolean;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [cancelConfirm, setCancelConfirm] = useState(false);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const running = job !== null && activeJob(job);
  const canStart = ready && project?.pdf.available && !running && !busy;
  async function operate(action: 'run' | 'resume' | 'cancel') {
    if (!project) return;
    setBusy(true);
    setError(null);
    try {
      if (action === 'cancel' && job) await api.cancelJob(job.id);
      else await api.createJob(project.id, action === 'resume' ? (job?.id ?? null) : null);
      setCancelConfirm(false);
      onChange();
    } catch (e) {
      setError(e instanceof Error ? e : new Error('任务操作失败。'));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="job-actions-wrapper">
      <div className="job-actions">
        {job && <span className={`badge job-${job.status}`}>{jobStatusLabels[job.status]}</span>}
        {running ? (
          <button type="button" disabled={busy} onClick={() => setCancelConfirm(true)}>
            <Square size={13} />
            取消任务
          </button>
        ) : (
          <>
            {job?.can_resume && (
              <button
                type="button"
                className={compact ? 'primary' : undefined}
                disabled={!canStart}
                onClick={() => void operate('resume')}
              >
                <RotateCcw size={14} />
                恢复任务
              </button>
            )}
            {!(compact && job?.can_resume) && (
              <button
                className="primary"
                type="button"
                disabled={!canStart}
                title={
                  !project
                    ? '请先选择项目'
                    : !project.pdf.available
                      ? '请先补充原始 PDF'
                      : !ready
                        ? '运行环境未就绪'
                        : '运行现有核心提取链，不调用付费建议模型'
                }
                onClick={() => void operate('run')}
              >
                <Play size={14} />
                {busy ? '正在提交…' : '运行提取'}
              </button>
            )}
          </>
        )}
        {compact && job && (
          <button
            type="button"
            className="toolbar-button"
            aria-label="任务详情"
            title="任务详情"
            onClick={() => setDetailsOpen(true)}
          >
            <MoreHorizontal size={14} />
          </button>
        )}
      </div>
      {error && <ErrorNotice error={error} onRetry={onChange} />}
      {job && !compact && <JobRecord job={job} />}
      {job && detailsOpen && (
        <Dialog title="任务详情" onClose={() => setDetailsOpen(false)}>
          <div className="dialog-body">
            <JobRecord job={job} expanded />
          </div>
        </Dialog>
      )}
      {cancelConfirm && (
        <Dialog title="取消当前提取任务？" onClose={() => setCancelConfirm(false)} busy={busy}>
          <div className="dialog-body">
            <p>
              仅取消此项目的当前任务。已保存的结果与缓存不被删除，是否可恢复以服务端真实状态为准。
            </p>
            {error && <ErrorNotice error={error} />}
            <footer className="dialog-actions">
              <button type="button" onClick={() => setCancelConfirm(false)} disabled={busy}>
                继续运行
              </button>
              <button
                type="button"
                className="danger-button"
                onClick={() => void operate('cancel')}
                disabled={busy}
              >
                {busy ? '正在取消…' : '确认取消此任务'}
              </button>
            </footer>
          </div>
        </Dialog>
      )}
    </div>
  );
}
