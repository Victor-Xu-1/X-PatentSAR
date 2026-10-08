import { useCallback, useEffect, useRef, useState } from 'react';
import { sarApi } from '../../api/sarApi';
import type { Dataset, Molecule } from '../../api/sarTypes';
import { useResource } from '../../hooks/useResource';
import { Loading } from '../../components/Feedback';
import { SARFailure } from './SARFailure';
import { useTranslation } from '../../i18n';
import { isActiveJob, jobLabels } from './presentation';
import { PageControls } from './PageControls';
import { PairTable } from './PairTable';
import { MutationNotice } from './MutationNotice';
import { MoleculeEvidence } from './MoleculeEvidence';
import { useSARMutation } from './useSARMutation';

function download(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}
export function SARResults({
  dataset,
  jobId,
  active,
  onJob,
  reference,
}: {
  dataset: Dataset;
  jobId: string;
  active: boolean;
  onJob: (id: string) => void;
  reference?: Molecule | null;
}) {
  const { t } = useTranslation();
  const [page, setPage] = useState(1);
  const [sourceId, setSourceId] = useState<string | null>(null);
  const mutation = useSARMutation();
  const exportMutation = useSARMutation();
  const exportController = useRef<AbortController | null>(null);
  useEffect(() => () => exportController.current?.abort(), []);
  useEffect(() => {
    if (!active) exportController.current?.abort();
  }, [active]);
  const loadJob = useCallback(
    (signal: AbortSignal) => sarApi.job(jobId, dataset.id, signal),
    [jobId, dataset.id],
  );
  const job = useResource(active ? `sar:job:${dataset.id}:${jobId}` : null, loadJob, {
    milliseconds: 2000,
    while: isActiveJob,
  });
  const loadPairs = useCallback(
    (signal: AbortSignal) => sarApi.pairs(jobId, dataset.id, page, signal),
    [jobId, dataset.id, page],
  );
  const pairs = useResource(
    active && job.data?.status === 'complete'
      ? `sar:pairs:${jobId}:${page}:${job.data.status}:${job.data.processed}:${job.data.stale}`
      : null,
    loadPairs,
  );
  const loadSource = useCallback(
    (signal: AbortSignal) => sarApi.drawing(dataset.id, sourceId ?? '', signal),
    [dataset.id, sourceId],
  );
  const source = useResource(
    active && sourceId ? `sar:source:${dataset.id}:${sourceId}` : null,
    loadSource,
  );
  const current = job.data && !job.data.stale && !dataset.stale;
  function refresh() {
    job.reload();
    pairs.reload();
    source.reload();
  }
  return (
    <section className="sar-panel" aria-label={t('参考比较结果')}>
      <div className="sar-section-heading">
        <h2>{t('参考比较结果')}</h2>
        <button type="button" onClick={refresh}>
          {t('刷新')}
        </button>
      </div>
      {job.loading && <Loading />}
      {job.error && <SARFailure error={job.error} onRetry={job.reload} />}
      {job.data && (
        <>
          <div className="sar-job-status">
            <strong>{t(jobLabels[job.data.status])}</strong>
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
                disabled={mutation.locked}
                onClick={() => {
                  void mutation.run(
                    () => sarApi.cancel(jobId, dataset.id),
                    () => refresh(),
                  );
                }}
              >
                {t('取消 SAR 任务')}
              </button>
            )}
            {!isActiveJob(job.data) &&
              ['cancelled', 'interrupted', 'failed'].includes(job.data.status) && (
                <button
                  type="button"
                  disabled={!current || mutation.locked}
                  onClick={() => {
                    const payload = { expected_input_sha256: job.data!.input_sha256 };
                    void mutation.run(
                      () => sarApi.resume(jobId, dataset.id, payload),
                      (resumed) => {
                        onJob(resumed.id);
                        refresh();
                      },
                    );
                  }}
                >
                  {t('继续 SAR 任务')}
                </button>
              )}
          </div>
          {(!current || pairs.data?.job.stale) && (
            <output className="sar-warning">
              {t('结果已过期，仅供历史核对；禁止续跑或作为当前结论。')}
            </output>
          )}
          {job.data.error_code && (
            <p role="alert">
              {job.data.error_code}: {job.data.error_message}
            </p>
          )}
          <p className="sar-hint">{t('任务状态与处理计数来自服务器，不代表科学验收。')}</p>
          {job.data.status !== 'complete' && <p>{t('比较结果仅在任务完成后发布。')}</p>}
          <MutationNotice mutation={mutation} />
          {pairs.loading && <Loading />}
          {pairs.error && <SARFailure error={pairs.error} onRetry={pairs.reload} />}
          {pairs.data && (
            <>
              <PairTable
                dataset={dataset}
                pairs={pairs.data}
                onSource={setSourceId}
                reference={reference ?? source.data?.molecule ?? null}
              />
              <PageControls
                page={page}
                total={pairs.data.total}
                onPage={setPage}
                disabled={pairs.loading}
              />
            </>
          )}
          <div className="sar-actions">
            {(['csv', 'json'] as const).map((format) => (
              <button
                key={format}
                type="button"
                disabled={exportMutation.busy || job.data!.status !== 'complete'}
                onClick={() => {
                  exportController.current?.abort();
                  const controller = new AbortController();
                  exportController.current = controller;
                  void exportMutation.run(
                    () => sarApi.export(jobId, format, controller.signal),
                    (blob) =>
                      download(blob, `sar-${jobId.replace(/[^a-zA-Z0-9_-]/g, '_')}.${format}`),
                  );
                }}
              >
                {t(format === 'csv' ? '导出全部 CSV' : '导出全部 JSON')}
              </button>
            ))}
          </div>
          <MutationNotice mutation={exportMutation} />
        </>
      )}
      {sourceId && (
        <div className="sar-source-detail">
          <div className="sar-section-heading">
            <h3>{t('来源详情')}</h3>
            <button type="button" onClick={() => setSourceId(null)}>
              {t('关闭对话框')}
            </button>
          </div>
          {source.loading && <Loading />}
          {source.error && <SARFailure error={source.error} onRetry={source.reload} />}
          {source.data && <MoleculeEvidence dataset={dataset} molecule={source.data.molecule} />}
        </div>
      )}
    </section>
  );
}
