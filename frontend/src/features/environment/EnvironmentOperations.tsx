import { useState } from 'react';
import type { EnvironmentOperation } from '../../api/environmentTypes';
import { activeEnvironmentOperation } from '../../model/environment';
import { dateText, jobStatusLabels } from '../../model/presentation';
import { Dialog } from '../../components/Dialog';
export function EnvironmentOperations({
  selected,
  selectionId,
  loading,
  catalogAvailable,
  operations,
  busy,
  readError,
  onSelect,
  onCancel,
  onReload,
}: {
  selected: EnvironmentOperation | null;
  selectionId: string | null;
  loading: boolean;
  catalogAvailable: boolean;
  operations: EnvironmentOperation[];
  busy: boolean;
  readError: boolean;
  onSelect: (id: string) => void;
  onCancel: (id: string) => Promise<unknown>;
  onReload: () => void;
}) {
  const [cancelTarget, setCancelTarget] = useState<EnvironmentOperation | null>(null);
  const canCancelTarget =
    cancelTarget?.id === selected?.id && activeEnvironmentOperation(selected) && !readError;
  return (
    <section className="panel environment-card environment-operations" aria-label="环境后台操作">
      <header className="environment-section-header">
        <div>
          <h2>后台操作与历史</h2>
          <p className="muted">持久化状态来自服务端，离开页面或刷新不会取消后台操作。</p>
        </div>
        <button type="button" disabled={loading || !selectionId} onClick={onReload}>
          刷新操作状态
        </button>
      </header>
      {selected ? (
        <article className="environment-operation-detail">
          <div className="environment-section-header">
            <div>
              <strong>{selected.action === 'install' ? '安装操作' : '检测操作'}</strong>
              <span className={`badge job-${selected.status}`}>
                {jobStatusLabels[selected.status]}
              </span>
            </div>
            {activeEnvironmentOperation(selected) && (
              <button
                type="button"
                disabled={busy || readError}
                onClick={() => setCancelTarget(selected)}
              >
                取消此环境操作
              </button>
            )}
          </div>
          <p className="operation-identity break-word">
            操作 {selected.id} · 请求 {selected.request_id}
          </p>
          <p className="break-word">安装目录：{selected.install_root}</p>
          <p>
            当前阶段：{selected.stage || '服务端尚未报告'} · 已完成{' '}
            {selected.completed_components.length}/{selected.component_ids.length} 个组件
          </p>
          <progress
            aria-label="环境操作已完成组件"
            value={selected.completed_components.length}
            max={Math.max(1, selected.component_ids.length)}
          />
          <small className="muted">
            创建 {dateText(selected.created_at)} · 开始 {dateText(selected.started_at)} · 结束{' '}
            {dateText(selected.finished_at)}
          </small>
          {readError && (
            <p className="info-banner">
              状态读取失败，当前显示上次已知状态。请刷新核对，不猜测完成进度。
            </p>
          )}
          {selected.error && (
            <output className="error-notice">
              {selected.error.code}：{selected.error.message}
            </output>
          )}
          {(selected.status === 'interrupted' ||
            selected.status === 'cancelled' ||
            selected.status === 'failed') && (
            <p className="info-banner">
              部分安装不代表可用。请重新检测组件，再明确选择是否重新安装；不自动恢复或放宽验证。
            </p>
          )}
          {selected.action === 'install' && selected.status === 'complete' && (
            <output className={selected.applied ? 'success-banner' : 'info-banner'}>
              {selected.applied
                ? '服务端已验证并应用环境配置。实际可用性仍以组件检查为准。'
                : '操作已结束，但配置尚未应用；请查看实际组件检查与日志。'}
            </output>
          )}
          <details open className="environment-log">
            <summary>操作日志（服务端最近 {Math.min(selected.log_tail.length, 200)} 行）</summary>
            <textarea
              readOnly
              rows={7}
              aria-label="环境操作日志"
              value={
                selected.log_tail.length
                  ? selected.log_tail.slice(-200).join('\n')
                  : '服务端尚未提供日志。'
              }
            />
          </details>
        </article>
      ) : (
        <p className="info-banner" role={loading ? 'status' : undefined}>
          {selectionId
            ? readError
              ? '选定操作读取失败，请刷新状态；不代表操作不存在或已取消。'
              : '正在读取持久化操作状态…'
            : catalogAvailable
              ? '暂无环境操作。检测或安装只在明确点击后启动。'
              : '尚未读取操作目录，不能确认是否有后台操作。请刷新环境目录；运行诊断仍可查看。'}
        </p>
      )}
      <details className="environment-history" open={operations.length > 0}>
        <summary>操作历史（{catalogAvailable ? operations.length : '未读取'}）</summary>
        {operations.length ? (
          <ul>
            {operations.map((operation) => (
              <li key={operation.id}>
                <button
                  type="button"
                  className={operation.id === selected?.id ? 'selected-operation' : ''}
                  onClick={() => onSelect(operation.id)}
                  aria-label={`查看环境操作 ${operation.id}`}
                >
                  <span>
                    {operation.action === 'install' ? '安装' : '检测'} ·{' '}
                    {jobStatusLabels[operation.status]}
                  </span>
                  <small>
                    {dateText(operation.created_at)} · {operation.id}
                  </small>
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted">
            {catalogAvailable ? '服务端尚无操作历史。' : '目录未读取，不以空列表冒充服务器历史。'}
          </p>
        )}
      </details>
      {cancelTarget && (
        <Dialog title="取消此环境后台操作？" busy={busy} onClose={() => setCancelTarget(null)}>
          <div className="dialog-body">
            <p>
              只取消操作 {cancelTarget.id}{' '}
              的已核实进程。保留持久化历史；不将未完成的组件标记为可用，也不停止其他服务。
            </p>
            {!canCancelTarget && (
              <p className="info-banner">
                所选操作或已知状态发生变化，不能提交旧的取消确认。请关闭后读取最新状态。
              </p>
            )}
            <footer className="dialog-actions">
              <button type="button" disabled={busy} onClick={() => setCancelTarget(null)}>
                继续运行
              </button>
              <button
                type="button"
                className="danger-button"
                disabled={busy || !canCancelTarget}
                onClick={() =>
                  void (async () => {
                    await onCancel(cancelTarget.id);
                    setCancelTarget(null);
                  })()
                }
              >
                确认取消此环境操作
              </button>
            </footer>
          </div>
        </Dialog>
      )}
    </section>
  );
}
