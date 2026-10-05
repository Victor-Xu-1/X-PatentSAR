import { useState } from 'react';
import type { useEnvironmentMutations } from './useEnvironmentMutations';
import { Dialog } from '../../components/Dialog';
export function RecoveryNotice({
  mutations,
}: {
  mutations: ReturnType<typeof useEnvironmentMutations>;
}) {
  const [confirm, setConfirm] = useState(false);
  if (!mutations.pending && !mutations.storageError) return null;
  return (
    <section className="environment-recovery info-banner" aria-label="环境操作状态恢复">
      <h2>配置状态待确认</h2>
      <p>上次操作结果尚未确认，请先检查状态。不会自动重复安装。</p>
      <div className="inline-actions">
        <button type="button" disabled={mutations.busy} onClick={() => void mutations.check()}>
          检查状态
        </button>
        {mutations.pending && mutations.checked && (
          <button type="button" disabled={mutations.busy} onClick={() => void mutations.retry()}>
            重试原操作
          </button>
        )}
      </div>
      {mutations.checked && <p>仍未确认结果。重试将沿用原操作，不会创建重复任务。</p>}
      {mutations.storageError && !mutations.pending && (
        <button
          type="button"
          disabled={!mutations.checked || mutations.busy}
          onClick={() => setConfirm(true)}
        >
          清除损坏的恢复记录
        </button>
      )}
      {confirm && (
        <Dialog title="清除本功能的损坏恢复记录？" onClose={() => setConfirm(false)}>
          <div className="dialog-body">
            <p>请先检查配置状态。只清除本页面的恢复信息，不停止后台任务或删除服务器记录。</p>
            <footer className="dialog-actions">
              <button type="button" onClick={() => setConfirm(false)}>
                保留记录
              </button>
              <button
                type="button"
                onClick={() => {
                  mutations.discardCorrupt();
                  setConfirm(false);
                }}
              >
                已核对状态，清除记录
              </button>
            </footer>
          </div>
        </Dialog>
      )}
    </section>
  );
}
