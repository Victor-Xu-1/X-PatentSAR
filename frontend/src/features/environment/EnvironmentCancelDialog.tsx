import { Dialog } from '../../components/Dialog';

export function EnvironmentCancelDialog({
  busy,
  enabled,
  onClose,
  onConfirm,
}: {
  busy: boolean;
  enabled: boolean;
  onClose: () => void;
  onConfirm: () => Promise<void>;
}) {
  return (
    <Dialog title="取消环境配置？" busy={busy} onClose={onClose}>
      <div className="dialog-body">
        <p>只取消当前环境配置，不影响其他任务，已有环境会保留。</p>
        {!enabled && <p className="info-banner">状态已变化，请关闭后重新确认。</p>}
        <footer className="dialog-actions">
          <button type="button" disabled={busy} onClick={onClose}>
            继续运行
          </button>
          <button
            type="button"
            className="danger-button"
            disabled={busy || !enabled}
            onClick={() => void onConfirm()}
          >
            确认取消此环境操作
          </button>
        </footer>
      </div>
    </Dialog>
  );
}
