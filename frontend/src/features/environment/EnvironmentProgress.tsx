import { useState } from 'react';
import type { EnvironmentOperation } from '../../api/environmentTypes';
import { activeEnvironmentOperation } from '../../model/environment';
import { EnvironmentCancelDialog } from './EnvironmentCancelDialog';

export function EnvironmentProgress({
  selected,
  selectionId,
  loading,
  busy,
  readError,
  onCancel,
  onReload,
}: {
  selected: EnvironmentOperation | null;
  selectionId: string | null;
  loading: boolean;
  busy: boolean;
  readError: boolean;
  onCancel: (id: string) => Promise<unknown>;
  onReload: () => void;
}) {
  const [target, setTarget] = useState<EnvironmentOperation | null>(null);
  const active = activeEnvironmentOperation(selected);
  if (target && (!active || target.id !== selected?.id)) setTarget(null);
  const canCancel = target?.id === selected?.id && active && !readError;
  if (!selected)
    return selectionId && (loading || readError) ? (
      <output className="info-banner">
        {readError ? '配置状态读取失败。' : '正在读取配置状态…'}
        <button type="button" disabled={loading} onClick={onReload}>
          刷新状态
        </button>
      </output>
    ) : null;
  if (
    !active &&
    selected.status === 'complete' &&
    (selected.action === 'inspect' || selected.applied)
  )
    return null;
  return (
    <section className="environment-progress" aria-label="环境配置进度">
      {active ? (
        <>
          <div className="environment-section-header">
            <span>
              {selected.action === 'install' ? '正在配置环境' : '正在检测环境'} ·{' '}
              {selected.completed_components.length}/{selected.component_ids.length}
            </span>
            <button type="button" disabled={busy || readError} onClick={() => setTarget(selected)}>
              取消此环境操作
            </button>
          </div>
          <progress
            aria-label="环境操作已完成组件"
            value={selected.completed_components.length}
            max={Math.max(1, selected.component_ids.length)}
          />
        </>
      ) : (
        <p className="info-banner">上次配置未完成，现有环境已保留。</p>
      )}
      {selected.error && <output className="error-notice">{selected.error.message}</output>}
      {!active &&
        selected.action === 'install' &&
        selected.status === 'complete' &&
        !selected.applied && (
          <output className="info-banner">配置尚未应用，请重新检测或部署。</output>
        )}
      {readError && (
        <div className="info-banner">
          状态读取失败，当前显示上次已知状态。
          <button type="button" disabled={loading} onClick={onReload}>
            刷新操作状态
          </button>
        </div>
      )}
      {target && (
        <EnvironmentCancelDialog
          busy={busy}
          enabled={canCancel}
          onClose={() => setTarget(null)}
          onConfirm={async () => {
            if (!canCancel) return;
            await onCancel(target.id);
            setTarget(null);
          }}
        />
      )}
    </section>
  );
}
