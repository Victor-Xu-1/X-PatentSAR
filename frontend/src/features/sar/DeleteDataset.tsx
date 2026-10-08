import { useCallback, useState } from 'react';
import type { Dataset } from '../../api/sarTypes';
import { sarApi } from '../../api/sarApi';
import { useSARResource } from './useSARResource';
import { Loading } from '../../components/Feedback';
import { SARFailure } from './SARFailure';
import { useTranslation } from '../../i18n';
import { isActiveJob } from './presentation';
import { MutationNotice } from './MutationNotice';
import { useSARMutation } from './useSARMutation';
export function DeleteDataset({
  dataset,
  active,
  onRemoved,
  disabled = false,
  scope = '',
}: {
  dataset: Dataset;
  active: boolean;
  onRemoved: () => void;
  disabled?: boolean;
  scope?: string;
}) {
  const { t } = useTranslation();
  const [confirm, setConfirm] = useState(false);
  const mutation = useSARMutation({ active, scope: JSON.stringify([scope, dataset.id]) });
  const load = useCallback((signal: AbortSignal) => sarApi.jobs(dataset.id, signal), [dataset.id]);
  const jobs = useSARResource(
    `sar:delete-jobs:${dataset.id}`,
    active && !disabled && confirm,
    load,
  );
  const inactive = jobs.validated && jobs.data !== null && !jobs.data.items.some(isActiveJob);
  return (
    <div className="sar-delete">
      {!confirm ? (
        <button type="button" disabled={!active || disabled} onClick={() => setConfirm(true)}>
          {t('移除数据集')}
        </button>
      ) : (
        <>
          <p>
            {t(
              '仅从日常列表软移除；来源、结果和审计保留，不释放磁盘空间。运行中的数据集不能移除。',
            )}
          </p>
          {jobs.loading && <Loading />}
          {jobs.error && <SARFailure error={jobs.error} onRetry={jobs.reload} />}
          <div className="sar-actions">
            <button
              type="button"
              disabled={disabled || !active || !inactive || mutation.locked}
              onClick={() => {
                void mutation.run(() => sarApi.removeDataset(dataset.id), onRemoved);
              }}
            >
              {t('确认软移除')}
            </button>
            <button type="button" disabled={mutation.locked} onClick={() => setConfirm(false)}>
              {t('取消')}
            </button>
            <button
              type="button"
              disabled={!active || disabled || mutation.busy}
              onClick={jobs.reload}
            >
              {t('刷新')}
            </button>
          </div>
          <MutationNotice mutation={mutation} disabled={!active || disabled || !jobs.validated} />
        </>
      )}
    </div>
  );
}
