import { useCallback, useEffect, useRef, useState } from 'react';
import { sarApi } from '../../../api/sarApi';
import { sarStudyApi } from '../../../api/sarStudyApi';
import type { Dataset } from '../../../api/sarTypes';
import { Loading } from '../../../components/Feedback';
import { useTranslation } from '../../../i18n';
import { isActiveJob, jobLabels } from '../presentation';
import { useSARResource } from '../useSARResource';
import { useSARMutation } from '../useSARMutation';
import { MutationNotice } from '../MutationNotice';
import { SARFailure } from '../SARFailure';
import { downloadSAR } from '../download';
import { StudyReportView } from './StudyReportView';
import { StudyReportInfo } from './StudyReportInfo';
import { ContractError } from '../../../api/validation';
export function StudyResults({
  dataset,
  jobId,
  active,
  disabled,
  scope,
  onJob,
}: {
  dataset: Dataset;
  jobId: string;
  active: boolean;
  disabled: boolean;
  scope: string;
  onJob: (id: string) => void;
}) {
  const { t } = useTranslation(),
    controller = useRef<AbortController | null>(null);
  const [infoOpen, setInfoOpen] = useState(false);
  const [format, setFormat] = useState<'csv' | 'json' | 'sdf' | 'html'>('csv');
  const loadJob = useCallback(
    async (signal: AbortSignal) => {
      const result = await sarApi.job(jobId, dataset.id, signal);
      if (result.kind !== 'study') throw new ContractError('$.study_job_identity');
      return result;
    },
    [jobId, dataset.id],
  );
  const job = useSARResource('sar:study-job:' + jobId, active && !disabled, loadJob, {
    milliseconds: 2000,
    while: isActiveJob,
  });
  const loadReport = useCallback(
    (signal: AbortSignal) => sarStudyApi.overview(jobId, dataset.id, signal),
    [jobId, dataset.id],
  );
  const overview = useSARResource(
    'sar:study-report:' + jobId,
    active && !disabled && job.validated && job.data?.status === 'complete',
    loadReport,
  );
  const mutation = useSARMutation({ active, scope: JSON.stringify([scope, dataset.id, jobId]) });
  const exporting = useSARMutation({ active, scope: JSON.stringify([scope, dataset.id, jobId]) });
  useEffect(() => () => controller.current?.abort(), []);
  useEffect(() => {
    if (!active || disabled) controller.current?.abort();
  }, [active, disabled]);
  const ready = active && !disabled && job.validated;
  const current = Boolean(
    job.data &&
    !job.data.stale &&
    !dataset.stale &&
    (!overview.data || overview.data.report.dataset_revision === dataset.revision),
  );
  function refresh() {
    job.reload();
    overview.reload();
  }
  return (
    <section className="sar-panel sar-study" aria-label={t('研究报告')}>
      <div className="sar-section-heading">
        <h2>{overview.data?.report.title ?? t('研究报告')}</h2>
        <button type="button" disabled={!active || disabled} onClick={refresh}>
          {t('刷新')}
        </button>
        {overview.data && (
          <button type="button" onClick={() => setInfoOpen(true)}>
            {t('研究详情')}
          </button>
        )}
      </div>
      {job.loading && <Loading />}
      {job.error && <SARFailure error={job.error} onRetry={job.reload} />}
      {job.data && (
        <div className="sar-job-status">
          <strong>{t(jobLabels[job.data.status])}</strong>
          <output hidden={job.data.status === 'complete'}>
            {t('已处理 {processed}/{total} · 已匹配 {matched}', {
              processed: job.data.processed,
              total: job.data.total,
              matched: job.data.matched,
            })}
          </output>
          {isActiveJob(job.data) && (
            <button
              type="button"
              disabled={!ready || mutation.locked}
              onClick={() => {
                void mutation.run(() => sarApi.cancel(jobId, dataset.id), refresh);
              }}
            >
              {t('取消 SAR 任务')}
            </button>
          )}
          {['failed', 'interrupted', 'cancelled'].includes(job.data.status) && (
            <button
              type="button"
              disabled={!ready || !current || mutation.locked}
              onClick={() => {
                const payload = { expected_input_sha256: job.data!.input_sha256 };
                void mutation.run(
                  () => sarApi.resume(jobId, dataset.id, payload),
                  (resumed) => {
                    refresh();
                    onJob(resumed.id);
                  },
                );
              }}
            >
              {t('继续 SAR 任务')}
            </button>
          )}
        </div>
      )}
      {job.data?.error_code && (
        <p role="alert">
          {job.data.error_code}: {job.data.error_message}
        </p>
      )}
      {job.data && !current && (
        <output
          className="sar-source-status is-review"
          title={t('结果已过期，仅供历史核对；禁止续跑或作为当前结论。')}
        >
          {t('历史研究')}
        </output>
      )}
      <MutationNotice mutation={mutation} disabled={!ready} />
      {job.data?.status !== 'complete' && (
        <p>{t('完整报告仅在任务完成后发布；部分进度不是科学结论。')}</p>
      )}
      {overview.loading && <Loading />}
      {overview.error && <SARFailure error={overview.error} onRetry={overview.reload} />}
      {overview.data && job.data?.status === 'complete' && (
        <>
          <div className="sar-report-context">
            <span className="sar-research-label" title={t('研究候选 · 非实验验收')}>
              {t('研究预览')}
            </span>
          </div>
          {infoOpen && (
            <StudyReportInfo
              report={overview.data.report}
              historical={!current}
              onClose={() => setInfoOpen(false)}
            />
          )}
          <StudyReportView
            report={overview.data.report}
            dataset={dataset}
            jobId={jobId}
            active={ready && overview.validated}
          />
        </>
      )}
      <div className="sar-actions">
        <label className="sr-only" htmlFor={'sar-export-' + jobId}>
          {t('导出格式')}
        </label>
        <select
          id={'sar-export-' + jobId}
          value={format}
          onChange={(e) => setFormat(e.target.value as typeof format)}
        >
          {(['csv', 'json', 'sdf', 'html'] as const).map((value) => (
            <option key={value} value={value}>
              {value.toUpperCase()}
            </option>
          ))}
        </select>
        <button
          type="button"
          aria-label={t('导出报告 {format}', { format: format.toUpperCase() })}
          disabled={!ready || job.data?.status !== 'complete' || exporting.busy}
          onClick={() => {
            controller.current?.abort();
            const read = new AbortController();
            controller.current = read;
            void exporting.run(
              () => sarStudyApi.export(jobId, format, read.signal),
              (blob) =>
                downloadSAR(
                  blob,
                  'sar-study-' + jobId.replace(/[^a-zA-Z0-9_-]/g, '_') + '.' + format,
                ),
            );
          }}
        >
          {t('导出')}
        </button>
      </div>
      <MutationNotice mutation={exporting} />
    </section>
  );
}
