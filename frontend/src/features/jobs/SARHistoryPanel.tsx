import { useCallback, useState } from 'react';
import { RefreshCw } from 'lucide-react';
import { sarApi } from '../../api/sarApi';
import type { SARHistoryPage } from '../../api/sarHistory';
import type { JobState } from '../../api/sarTypes';
import { useTranslation } from '../../i18n';
import { Empty, Loading } from '../../components/Feedback';
import { SARFailure } from '../sar/SARFailure';
import { useSARResource } from '../sar/useSARResource';
import { jobLabels } from '../sar/presentation';
import { GroupPager } from '../sar/study/GroupPager';
import { SARHistoryRow } from './SARHistoryRow';

const states: JobState[] = ['queued', 'running', 'complete', 'failed', 'cancelled', 'interrupted'];
const polling = { milliseconds: 3000, while: (page: SARHistoryPage) => page.active_count > 0 };
export function SARHistoryPanel({
  active,
  onOpen,
}: {
  active: boolean;
  onOpen: ((datasetId: string, jobId: string) => void) | undefined;
}) {
  const { t } = useTranslation();
  const [datasetId, setDataset] = useState('');
  const [status, setStatus] = useState<JobState | ''>('');
  const [page, setPage] = useState(1);
  const loadDatasets = useCallback((signal: AbortSignal) => sarApi.datasets(signal), []);
  const datasets = useSARResource('sar:history:datasets', active, loadDatasets);
  const load = useCallback(
    (signal: AbortSignal) => sarApi.history({ page, datasetId, status }, signal),
    [page, datasetId, status],
  );
  const jobs = useSARResource(
    JSON.stringify(['sar:history', page, datasetId, status]),
    active,
    load,
    polling,
  );
  if (
    datasets.validated &&
    datasetId &&
    !datasets.data!.items.some((item) => item.id === datasetId)
  ) {
    setDataset('');
    setPage(1);
  }
  if (jobs.validated && page > Math.max(1, Math.ceil(jobs.data!.total / 25)))
    setPage(Math.max(1, Math.ceil(jobs.data!.total / 25)));
  const ready = jobs.validated && datasets.validated;
  return (
    <section className="sar-task-history" aria-label={t('SAR 分析任务')} data-dialog-focus-scope>
      <header className="page-header job-panel-toolbar">
        <div className="inline-actions">
          <select
            aria-label={t('筛选 SAR 数据集')}
            disabled={!datasets.validated}
            value={datasetId}
            onChange={(event) => {
              setDataset(event.target.value);
              setPage(1);
            }}
          >
            <option value="">{t('全部数据集')}</option>
            {datasets.data?.items.map((item) => (
              <option key={item.id} value={item.id}>
                {item.title}
              </option>
            ))}
          </select>
          <select
            aria-label={t('筛选 SAR 状态')}
            value={status}
            onChange={(event) => {
              setStatus(event.target.value as JobState | '');
              setPage(1);
            }}
          >
            <option value="">{t('全部状态')}</option>
            {states.map((value) => (
              <option key={value} value={value}>
                {t(jobLabels[value])}
              </option>
            ))}
          </select>
          <button
            type="button"
            aria-label={t('刷新 SAR 任务')}
            data-dialog-focus-fallback
            disabled={jobs.loading || datasets.loading}
            onClick={() => {
              jobs.reload();
              datasets.reload();
            }}
          >
            <RefreshCw size={16} aria-hidden="true" />
          </button>
        </div>
      </header>
      {datasets.error && <SARFailure error={datasets.error} onRetry={datasets.reload} />}
      {jobs.error && <SARFailure error={jobs.error} onRetry={jobs.reload} />}
      {jobs.loading && !jobs.data && <Loading />}
      {jobs.validated && !jobs.data!.items.length && (
        <Empty
          title="暂无 SAR 分析任务"
          description={
            datasetId || status
              ? '可切换数据集或状态查看其他任务。'
              : '在 SAR 分析中创建的任务会显示在这里。'
          }
        />
      )}
      {Boolean(jobs.data?.items.length) && (
        <ul
          className="job-history sar-history-list"
          aria-label={t('SAR 历史任务')}
          aria-busy={jobs.loading}
        >
          {jobs.data!.items.map((item) => (
            <SARHistoryRow
              key={item.job.id}
              item={item}
              active={active}
              verified={ready}
              onOpen={onOpen}
              onRemoved={jobs.reload}
            />
          ))}
        </ul>
      )}
      {jobs.data && (
        <footer className="sar-history-footer">
          <small>
            {t(jobs.data.total === 1 ? '共 1 条任务' : '共 {count} 条任务', {
              count: jobs.data.total,
            })}
          </small>
          <GroupPager page={page} total={jobs.data.total} size={25} onPage={setPage} />
        </footer>
      )}
    </section>
  );
}
