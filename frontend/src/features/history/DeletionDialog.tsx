import type { HistoryAction, HistoryEntry, HistoryTarget } from '../../api/historyTypes';
import { Dialog } from '../../components/Dialog';
import { ErrorNotice, Loading } from '../../components/Feedback';
import { deletionScope, historyLabels, retentionNotice } from './historyPresentation';
import { useHistoryMutation } from './useHistoryMutation';

export function DeletionDialog({
  target,
  action,
  onClose,
  onChanged,
}: {
  target: HistoryTarget;
  action: HistoryAction;
  onClose: () => void;
  onChanged: (entry: HistoryEntry) => void;
}) {
  const state = useHistoryMutation(target, action, onChanged);
  const restoring = action === 'restore';
  return (
    <Dialog
      title={`${restoring ? '恢复' : '删除'}${historyLabels[target.kind]}？`}
      onClose={onClose}
      busy={state.busy}
      className="history-mutation-dialog"
    >
      <div className="dialog-body" aria-busy={state.busy || state.loading}>
        <strong className="history-target-title">{state.entry?.title ?? target.title}</strong>
        <p>
          {restoring
            ? '将此记录恢复到日常视图。项目在回收站时，请先恢复项目，再恢复其下的记录。'
            : deletionScope[target.kind]}
        </p>
        <p className="muted">{retentionNotice}</p>
        {state.loading && <Loading label="正在核对服务端状态…" />}
        {state.error && <ErrorNotice error={state.error} />}
        {state.needsRefresh && <output>提交已停止；请先刷新核对状态，再决定是否重新确认。</output>}
        {!state.loading &&
          !state.needsRefresh &&
          state.entry &&
          !state.completed &&
          !(restoring ? state.entry.can_restore : state.entry.can_delete) && (
            <output>{state.entry.blocked_reason ?? '服务端当前不允许此操作。'}</output>
          )}
        {state.completed && !state.needsRefresh && (
          <output className="info-banner">{restoring ? '记录已恢复。' : '记录已在回收站。'}</output>
        )}
        <footer className="dialog-actions">
          <button type="button" data-initial-focus disabled={state.busy} onClick={onClose}>
            {state.completed ? '关闭' : '取消'}
          </button>
          <button type="button" disabled={state.busy || state.loading} onClick={state.refresh}>
            刷新核对状态
          </button>
          <button
            type="button"
            className={restoring ? 'primary' : 'danger-button'}
            disabled={!state.canConfirm}
            onClick={() => void state.confirm()}
          >
            {state.busy ? '正在提交…' : restoring ? '确认恢复' : '确认移入回收站'}
          </button>
        </footer>
      </div>
    </Dialog>
  );
}
