import type { Dataset, JobList } from '../../api/sarTypes';
import type { Resource } from '../../hooks/useResource';
import { Empty, Loading } from '../../components/Feedback';
import { SARFailure } from './SARFailure';
import { useTranslation } from '../../i18n';
import { jobLabels } from './presentation';
import { dateText } from '../../model/presentation';
import { DeleteSARJob } from './DeleteSARJob';
export function SARJobs({
  dataset,
  resource,
  selectedId,
  onSelect,
  onRemoved,
  disabled = false,
  active = true,
  scope = '',
}: {
  dataset: Dataset;
  resource: Resource<JobList>;
  selectedId: string | null;
  onSelect: (id: string) => void;
  onRemoved?: (id: string) => void;
  disabled?: boolean;
  active?: boolean;
  scope?: string;
}) {
  const { t } = useTranslation();
  return (
    <section className="sar-panel" aria-label={t('SAR 任务')}>
      <div className="sar-section-heading">
        <h2>{t('SAR 任务')}</h2>
        <button type="button" onClick={resource.reload} disabled={resource.loading}>
          {t('刷新')}
        </button>
      </div>
      {resource.loading && <Loading />}
      {resource.error && <SARFailure error={resource.error} onRetry={resource.reload} />}
      {resource.data && !resource.data.items.length && (
        <Empty
          title="尚无参考比较任务"
          description="保存区域并明确选择指标和方向后，才能启动任务。"
        />
      )}
      <ul className="sar-job-list">
        {resource.data?.items.map((job) => (
          <li key={job.id}>
            <button
              type="button"
              aria-pressed={selectedId === job.id}
              disabled={disabled}
              onClick={() => onSelect(job.id)}
            >
              <span>
                {job.kind === 'study'
                  ? t('完整 SAR 研究')
                  : (dataset.metrics.find((metric) => metric.id === job.metric_id)?.name ??
                    job.metric_id)}
              </span>
              <span>{t(jobLabels[job.status])}</span>
              <time dateTime={job.created_at}>{dateText(job.created_at)}</time>
              <small>
                {t('已处理 {processed}/{total} · 已匹配 {matched}', {
                  processed: job.processed,
                  total: job.total,
                  matched: job.matched,
                })}
              </small>
              {job.stale && (
                <small>{t('结果已过期，仅供历史核对；禁止续跑或作为当前结论。')}</small>
              )}
            </button>
            {onRemoved && (
              <DeleteSARJob
                job={job}
                disabled={disabled}
                active={active}
                scope={scope}
                title={
                  job.kind === 'study'
                    ? t('完整 SAR 研究')
                    : (dataset.metrics.find((metric) => metric.id === job.metric_id)?.name ??
                      job.metric_id)
                }
                onRemoved={onRemoved}
              />
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
