import { FlaskConical } from 'lucide-react';
import type { SARHistoryItem } from '../../api/sarHistory';
import { useTranslation } from '../../i18n';
import { dateText } from '../../model/presentation';
import { DeleteSARJob } from '../sar/DeleteSARJob';
import { jobLabels } from '../sar/presentation';

export function SARHistoryRow({
  item,
  active,
  verified,
  onOpen,
  onRemoved,
}: {
  item: SARHistoryItem;
  active: boolean;
  verified: boolean;
  onOpen: ((datasetId: string, jobId: string) => void) | undefined;
  onRemoved: (id: string) => void;
}) {
  const { t } = useTranslation();
  const { job } = item;
  const title = item.title || t(job.kind === 'study' ? '完整 SAR 研究' : '单参考比较');
  return (
    <li className="sar-history-card" data-job-id={job.id}>
      <span className="job-file-icon" aria-hidden="true">
        <FlaskConical size={19} />
      </span>
      <div className="sar-history-name">
        <button
          type="button"
          className="link-button"
          disabled={!verified || !onOpen}
          onClick={() => onOpen?.(job.dataset_id, job.id)}
        >
          {title}
        </button>
        {item.dataset_title !== title && <small>{item.dataset_title}</small>}
        <time dateTime={job.created_at}>{dateText(job.created_at)}</time>
      </div>
      <div className="sar-history-status">
        <span className={'status-badge ' + job.status}>{t(jobLabels[job.status])}</span>
        {job.stale && <small>{t('历史版本')}</small>}
      </div>
      <div className="sar-history-actions">
        <button
          type="button"
          disabled={!verified || !onOpen}
          onClick={() => onOpen?.(job.dataset_id, job.id)}
        >
          {t(job.status === 'complete' ? '查看结果' : '查看任务')}
        </button>
        <DeleteSARJob
          job={job}
          title={title}
          active={active}
          disabled={!verified}
          scope="task-history"
          onRemoved={onRemoved}
        />
      </div>
    </li>
  );
}
