import { useCallback, useEffect, useRef, useState } from 'react';
import { sarApi } from '../../../api/sarApi';
import { sarStudyApi } from '../../../api/sarStudyApi';
import type { Dataset } from '../../../api/sarTypes';
import { Loading } from '../../../components/Feedback';
import { useTranslation } from '../../../i18n';
import { isActiveJob } from '../presentation';
import { useSARResource } from '../useSARResource';
import { useSARMutation } from '../useSARMutation';
import { MutationNotice } from '../MutationNotice';
import { SARFailure } from '../SARFailure';
import { downloadSAR } from '../download';
import { StudyReportView } from './StudyReportView';
import { StudyReportInfo } from './StudyReportInfo';
import { StudyReportHeader } from './StudyReportHeader';
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
      <StudyReportHeader
        title={overview.data?.report.title ?? null}
        status={job.data?.status ?? null}
        historical={Boolean(job.data && !current)}
        research={Boolean(overview.data && job.data?.status === 'complete')}
        disabled={!active || disabled}
        onRefresh={refresh}
        onDetails={overview.data ? () => setInfoOpen(true) : null}
      />
      {job.loading && <Loading />}
      {job.error && <SARFailure error={job.error} onRetry={job.reload} />}
      {job.data && job.data.status !== 'complete' && (
        <div className="sar-job-status">
          <output>
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
      <MutationNotice mutation={mutation} disabled={!ready} />
      {job.data?.status !== 'complete' && (
        <p>{t('完整报告仅在任务完成后发布；部分进度不是科学结论。')}</p>
      )}
      {overview.loading && <Loading />}
      {overview.error && <SARFailure error={overview.error} onRetry={overview.reload} />}
      {overview.data && job.data?.status === 'complete' && (
        <>
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
      <div className="sar-actions sar-export-actions">
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
