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
      <h2>有待核对的环境操作</h2>
      <p>
        请求结果尚未确认，不代表安装失败或已取消。未自动重放；先读取服务器持久化状态，再决定下一步。
      </p>
      {mutations.pending?.kind === 'operation' && (
        <p className="break-word">
          保留的请求 ID：<code>{mutations.pending.request.request_id}</code>
        </p>
      )}
      <div className="inline-actions">
        <button type="button" disabled={mutations.busy} onClick={() => void mutations.check()}>
          检查服务器状态
        </button>
        {mutations.pending && mutations.checked && (
          <button type="button" disabled={mutations.busy} onClick={() => void mutations.retry()}>
            {mutations.pending.kind === 'operation' ? '使用相同请求 ID 重试' : '核对后重试原请求'}
          </button>
        )}
      </div>
      {mutations.checked && (
        <p>本次可见状态尚未确认请求结果；重试仍使用原始请求参数与幂等 ID，不创建另一份安装计划。</p>
      )}
      {mutations.storageError && !mutations.pending && (
        <button
          type="button"
          disabled={!mutations.checked || mutations.busy}
          onClick={() => setConfirm(true)}
        >
          核对历史后清除损坏恢复记录
        </button>
      )}
      {confirm && (
        <Dialog title="清除本功能的损坏恢复记录？" onClose={() => setConfirm(false)}>
          <div className="dialog-body">
            <p>
              请先检查下方服务器操作历史。只清除环境管理的本地恢复记录，不删除服务器操作，也不取消后台进程。
            </p>
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
                已核对历史，清除恢复记录
              </button>
            </footer>
          </div>
        </Dialog>
      )}
    </section>
  );
}
