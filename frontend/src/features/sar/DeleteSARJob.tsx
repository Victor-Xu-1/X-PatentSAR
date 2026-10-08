import { useState } from 'react';
import type { SARJob } from '../../api/sarTypes';
import { sarApi } from '../../api/sarApi';
import { ApiError } from '../../api/errors';
import { Dialog } from '../../components/Dialog';
import { useTranslation } from '../../i18n';
import { dateText } from '../../model/presentation';
import { isActiveJob } from './presentation';
import { MutationNotice } from './MutationNotice';
import { useSARMutation } from './useSARMutation';

export function DeleteSARJob({
  job,
  title,
  onRemoved,
  disabled = false,
  active = true,
  scope = '',
}: {
  job: SARJob;
  title: string;
  onRemoved: (id: string) => void;
  disabled?: boolean;
  active?: boolean;
  scope?: string;
}) {
  const { t } = useTranslation();
  const [confirm, setConfirm] = useState(false);
  const mutation = useSARMutation({
    active,
    scope: JSON.stringify([scope, job.dataset_id, job.id]),
  });
  const blocked =
    job.error_code === 'sar_process_unverified' ||
    (mutation.error instanceof ApiError && mutation.error.code === 'sar_process_unverified');
  if (isActiveJob(job)) return null;
  return (
    <>
      <button
        type="button"
        disabled={!active || disabled || job.error_code === 'sar_process_unverified'}
        onClick={() => setConfirm(true)}
      >
        {t('移除 SAR 任务')}
      </button>
      {job.error_code === 'sar_process_unverified' && (
        <small>{t('SAR 进程清理尚未验证，任务不可移除。')}</small>
      )}
      {confirm && (
        <Dialog
          title={t('移除 SAR 任务')}
          busy={mutation.busy}
          onClose={() => {
            if (!mutation.busy) {
              setConfirm(false);
              mutation.clearError();
            }
          }}
        >
          <div className="dialog-body">
            <p>
              <strong>{title}</strong> ·{' '}
              <time dateTime={job.created_at}>{dateText(job.created_at)}</time>
            </p>
            <p>
              {t('只软移除这条 SAR 任务记录。数据集、来源、结果和审计字节保留，不释放磁盘空间。')}
            </p>
            {blocked && <p role="alert">{t('SAR 进程清理尚未验证，任务不可移除。')}</p>}
            <MutationNotice mutation={mutation} disabled={!active || disabled} />
          </div>
          <footer className="dialog-actions">
            <button
              type="button"
              disabled={mutation.busy}
              onClick={() => {
                setConfirm(false);
                mutation.clearError();
              }}
            >
              {t('取消')}
            </button>
            <button
              type="button"
              disabled={!active || disabled || mutation.locked || blocked}
              onClick={() => {
                void mutation.run(
                  () => sarApi.removeJob(job.id),
                  () => {
                    setConfirm(false);
                    onRemoved(job.id);
                  },
                );
              }}
            >
              {t('确认软移除')}
            </button>
          </footer>
        </Dialog>
      )}
    </>
  );
}
