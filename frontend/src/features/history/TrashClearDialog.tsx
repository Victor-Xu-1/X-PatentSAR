import { Dialog } from '../../components/Dialog';
import { ErrorNotice, Loading } from '../../components/Feedback';
import { historyKinds } from '../../api/historyTypes';
import { useTranslation } from '../../i18n';
import { historyLabels } from './historyPresentation';
import { useTrashClear } from './useTrashClear';

export function TrashClearDialog({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const { t } = useTranslation();
  const state = useTrashClear(onDone);
  return (
    <Dialog
      title={t('清空回收站？')}
      onClose={onClose}
      busy={state.busy}
      className="history-mutation-dialog"
    >
      <div className="dialog-body" aria-busy={state.busy || state.loading}>
        {state.loading && <Loading label={t('正在核对全部回收站…')} />}
        {state.error && <ErrorNotice error={state.error} />}
        {state.receipt ? (
          <div className="info-banner">
            <output>{t('已永久移除 {count} 条记录。', { count: state.receipt.cleared })}</output>
            <p>
              {t('已清理 {deleted}/{total} 个文件。', {
                deleted: state.receipt.files_deleted,
                total: state.receipt.files_total,
              })}
            </p>
            {state.receipt.status === 'cleanup_pending' && (
              <output>{t('文件清理未完成，可继续原操作。')}</output>
            )}
          </div>
        ) : (
          state.plan && (
            <>
              <strong>
                {t('全部类型、全部分页，共 {count} 条记录。', { count: state.plan.total })}
              </strong>
              <ul className="trash-clear-counts">
                {historyKinds
                  .filter((kind) => state.plan!.counts[kind])
                  .map((kind) => (
                    <li key={kind}>
                      <span>{t(historyLabels[kind])}</span>
                      <strong>{state.plan!.counts[kind]}</strong>
                    </li>
                  ))}
              </ul>
              <p>{t('可清理 {count} 个未引用文件。', { count: state.plan.files_total })}</p>
              {state.plan.retained_targets > 0 && (
                <p>
                  {t('{count} 组被引用、导入或无法核实的资产将保留。', {
                    count: state.plan.retained_targets,
                  })}
                </p>
              )}
              {state.plan.blocked > 0 && (
                <output>
                  {t('{count} 条记录仍有活动或未核实的进程，暂不能清空。', {
                    count: state.plan.blocked,
                  })}
                </output>
              )}
            </>
          )
        )}
        <p>
          {t(
            '清空不可撤销。只删除已核实未被引用的原始文件和产物；被引用的文件、共享环境和审计保留。',
          )}
        </p>
        {state.needsCheck && <output>{t('清空结果尚未确认。请先核对，不会自动重复删除。')}</output>}
        <footer className="dialog-actions">
          <button type="button" data-initial-focus disabled={state.busy} onClick={onClose}>
            {t(state.receipt ? '关闭' : '取消')}
          </button>
          {state.receipt?.status !== 'complete' && (
            <button type="button" disabled={state.busy || state.loading} onClick={state.check}>
              {t('核对回收站')}
            </button>
          )}
          {state.receipt?.status !== 'complete' && !state.needsCheck && (
            <button
              type="button"
              className="danger-button"
              disabled={!state.canConfirm}
              onClick={() => void state.confirm()}
            >
              {t(
                state.busy
                  ? '正在提交…'
                  : state.receipt?.status === 'cleanup_pending'
                    ? '继续清理文件'
                    : state.retrying
                      ? '重试此清空操作'
                      : '确认清空全部',
              )}
            </button>
          )}
        </footer>
      </div>
    </Dialog>
  );
}
