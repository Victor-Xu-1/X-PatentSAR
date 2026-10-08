import { useEffect, useRef, useState } from 'react';
import { api } from '../../api';
import { ApiError } from '../../api/errors';
import { llmApi } from '../../api/llmApi';
import type { LLMSettings } from '../../api/llmTypes';
import type { Job } from '../../api/types';
import { Dialog } from '../../components/Dialog';
import { ErrorNotice, Loading } from '../../components/Feedback';
import { activeJob } from '../../model/presentation';
import {
  llmAuthorizationError,
  llmReason,
  llmRecoveryStatusLabels,
  llmRequestError,
} from '../llm/llmMessages';

export interface LLMRecoveryControls {
  eligible: boolean;
  disabled: boolean;
  acquire: () => boolean;
  release: () => void;
  awaitRefresh: () => void;
  onChange: () => void;
}

export function LLMRecovery({
  job,
  controls,
}: {
  job: Job;
  controls?: LLMRecoveryControls | undefined;
}) {
  const recovery = job.llm_recovery;
  if (!recovery) return null;
  return (
    <section className="llm-recovery" aria-label="LLM 局部修复">
      <h3>{llmRecoveryStatusLabels[recovery.status]}</h3>
      {recovery.reason !== null && <p>{llmReason(recovery.reason)}</p>}
      <p>
        {recovery.remaining_calls === null
          ? '剩余调用次数未知'
          : `剩余调用 ${recovery.remaining_calls} 次`}
        {recovery.retry_after_seconds !== null &&
          ` · 本次重试等待 ${recovery.retry_after_seconds} 秒（服务端观察）`}
        {recovery.status === 'cooldown' &&
          recovery.retry_after_seconds === null &&
          ' · 重试等待时间未知'}
      </p>
      <p>
        <a href="#/settings">配置 LLM API</a>
      </p>
      {controls && <LLMAuthorization key={job.id} job={job} controls={controls} />}
    </section>
  );
}

function LLMAuthorization({ job, controls }: { job: Job; controls: LLMRecoveryControls }) {
  const [phase, setPhase] = useState<'idle' | 'reading' | 'confirming' | 'writing'>('idle');
  const [settings, setSettings] = useState<LLMSettings | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [needsRefresh, setNeedsRefresh] = useState(false);
  const [submittedJob, setSubmittedJob] = useState<Job | null>(null);
  const [saved, setSaved] = useState(false);
  const reading = useRef<AbortController | null>(null);
  const release = useRef<(() => void) | null>(null);
  const writing = useRef(false);
  const alive = useRef(true);
  const opener = useRef<HTMLButtonElement>(null);
  const refreshAction = useRef<HTMLButtonElement>(null);
  const restoreFocus = useRef(false);
  const eligible =
    controls.eligible &&
    job.llm_recovery?.can_reauthorize === true &&
    job.can_resume &&
    !activeJob(job) &&
    ['interrupted', 'failed', 'cancelled'].includes(job.status);

  function unlock() {
    release.current?.();
    release.current = null;
  }
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      reading.current?.abort();
      release.current?.();
      release.current = null;
    };
  }, []);
  useEffect(() => {
    if (phase === 'idle' && restoreFocus.current) {
      restoreFocus.current = false;
      // Native Chrome loses focus when the opener becomes disabled before the
      // shared Dialog mounts. Restore only after React has enabled the control.
      (opener.current ?? refreshAction.current)?.focus();
    }
  }, [phase]);

  async function open() {
    if (
      !eligible ||
      controls.disabled ||
      needsRefresh ||
      submittedJob === job ||
      release.current ||
      !controls.acquire()
    )
      return;
    release.current = controls.release;
    const request = new AbortController();
    reading.current = request;
    setPhase('reading');
    setSettings(null);
    setError(null);
    setSaved(false);
    try {
      const current = await llmApi.settings(request.signal);
      if (request.signal.aborted || !alive.current) return;
      setSettings(current);
      if (current.status !== 'ready')
        setError(new Error('请先在环境管理中保存并启用完整的 API 配置与外发授权。'));
    } catch (failure) {
      if (request.signal.aborted || !alive.current) return;
      setError(llmRequestError(failure));
    } finally {
      if (reading.current === request && !request.signal.aborted && alive.current) {
        reading.current = null;
        setPhase('confirming');
      }
    }
  }

  function close() {
    if (writing.current) return;
    reading.current?.abort();
    reading.current = null;
    unlock();
    restoreFocus.current = true;
    setPhase('idle');
    if (!needsRefresh) setError(null);
  }
  function refresh() {
    close();
    setSubmittedJob(job); // Only a fresh job DTO can reconcile the write.
    setNeedsRefresh(false);
    setSettings(null);
    setError(null);
    controls.onChange();
  }
  async function submit() {
    if (
      writing.current ||
      phase !== 'confirming' ||
      !release.current ||
      !eligible ||
      needsRefresh ||
      settings?.status !== 'ready'
    )
      return;
    writing.current = true;
    setPhase('writing');
    setError(null);
    try {
      const result = await api.reauthorizeJobLLM(job.id, settings.revision);
      if (result.project_id !== job.project_id)
        throw new ApiError(200, 'invalid_write_response', '授权响应不属于当前项目。', true);
      if (!alive.current) return;
      setSubmittedJob(job);
      controls.awaitRefresh();
      setSaved(true);
      setPhase('idle');
      unlock();
      controls.onChange();
    } catch (failure) {
      if (!alive.current) return;
      setError(llmAuthorizationError(failure));
      setNeedsRefresh(true);
      controls.awaitRefresh();
      setPhase('confirming');
    } finally {
      writing.current = false;
    }
  }

  return (
    <>
      {eligible && (
        <button
          ref={opener}
          type="button"
          disabled={controls.disabled || needsRefresh || submittedJob === job}
          onClick={() => void open()}
        >
          更新 API 授权
        </button>
      )}
      {saved && (
        <output aria-live="polite">API 授权已更新，未开始提取。核对后可手动继续提取。</output>
      )}
      {phase === 'idle' && error && <ErrorNotice error={error} />}
      {phase === 'idle' && needsRefresh && (
        <button ref={refreshAction} type="button" onClick={refresh}>
          刷新核对任务与配置
        </button>
      )}
      {phase !== 'idle' && (
        <Dialog title="更新此任务的 API 授权？" onClose={close} busy={phase === 'writing'}>
          <div className="dialog-body">
            <p>
              只允许这个任务使用已保存且相同服务、模型和协议的凭据。不重置配额、不开始提取、不调用模型；成功后仅刷新，需手动继续提取。
            </p>
            {phase === 'reading' && <Loading label="正在读取当前 API 配置…" />}
            {settings && (
              <dl className="job-dates">
                <div>
                  <dt>服务</dt>
                  <dd>{settings.endpoint || '未配置'}</dd>
                </div>
                <div>
                  <dt>模型</dt>
                  <dd>{settings.model || '未配置'}</dd>
                </div>
                <div>
                  <dt>协议</dt>
                  <dd>{settings.protocol}</dd>
                </div>
              </dl>
            )}
            <p className="muted">
              <a href="#/settings">前往环境管理核对配置</a> · 已配置不代表模型验收。
            </p>
            {!eligible && !needsRefresh && <p role="alert">任务状态已改变，请刷新核对后再操作。</p>}
            {error && <ErrorNotice error={error} />}
            <footer className="dialog-actions">
              <button
                type="button"
                onClick={close}
                disabled={phase === 'writing'}
                data-initial-focus
              >
                取消
              </button>
              {needsRefresh || !eligible ? (
                <button type="button" onClick={refresh} disabled={phase === 'writing'}>
                  刷新核对任务与配置
                </button>
              ) : (
                <button
                  type="button"
                  className="primary"
                  onClick={() => void submit()}
                  disabled={phase !== 'confirming' || settings?.status !== 'ready'}
                >
                  {phase === 'writing' ? '正在更新…' : '确认更新授权'}
                </button>
              )}
            </footer>
          </div>
        </Dialog>
      )}
    </>
  );
}
