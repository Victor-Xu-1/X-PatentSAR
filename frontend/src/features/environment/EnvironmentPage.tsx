import { useState } from 'react';
import { RefreshCw, ScanLine } from 'lucide-react';
import type { Identity } from '../../api/types';
import type { EnvironmentComponentId } from '../../api/environmentTypes';
import { ApiError } from '../../api/errors';
import { activeEnvironmentOperation, selectedEnvironmentComponents } from '../../model/environment';
import {
  canInstallEnvironmentPlan,
  isEnvironmentInstallPlanCurrent,
} from '../../model/environmentStatus';
import { dateText } from '../../model/presentation';
import { ErrorNotice, Loading } from '../../components/Feedback';
import { useEnvironmentWorkspace } from './useEnvironmentWorkspace';
import { InstallLocation } from './InstallLocation';
import { RecommendedBundles } from './RecommendedBundles';
import { ComponentLibrary } from './ComponentLibrary';
import { InstallConfirmation } from './InstallConfirmation';
import type { InstallPlan } from './InstallConfirmation';
import { RecoveryNotice } from './RecoveryNotice';
import { EnvironmentOperations } from './EnvironmentOperations';
import { RuntimeDiagnostics } from './RuntimeDiagnostics';

export function EnvironmentPage({
  operationId,
  onOperation,
  product,
}: {
  operationId: string | null;
  onOperation: (id: string) => void;
  product: Identity;
}) {
  const workspace = useEnvironmentWorkspace(operationId, onOperation);
  const { catalog, mutations } = workspace;
  const data = catalog.data;
  const [plan, setPlan] = useState<InstallPlan | null>(null),
    [selectionError, setSelectionError] = useState<Error | null>(null);
  const blocked =
    mutations.busy ||
    Boolean(mutations.pending) ||
    mutations.storageError ||
    activeEnvironmentOperation(data?.active_operation ?? null) ||
    activeEnvironmentOperation(workspace.selected);
  const disabled = blocked || !data?.settings.enabled || catalog.loading;
  const planCurrent = Boolean(
    plan &&
    data &&
    !blocked &&
    data.settings.enabled &&
    isEnvironmentInstallPlanCurrent(plan.components, plan.requested, data.components),
  );
  function install(ids: EnvironmentComponentId[]) {
    if (!data || disabled) return;
    setSelectionError(null);
    try {
      const components = selectedEnvironmentComponents(data.components, ids);
      if (!canInstallEnvironmentPlan(components))
        throw new Error('所选组件已安装、需先检测或不支持安装，请刷新并核对；不重复安装已有组件。');
      setPlan({ components, settings: data.settings, requested: [...ids] });
    } catch (e) {
      setSelectionError(e instanceof Error ? e : new Error('安装选择无效。'));
    }
  }
  return (
    <section className="management-page environment-page">
      <header className="page-header">
        <div>
          <h1>环境管理</h1>
        </div>
        <button type="button" onClick={workspace.refresh} disabled={catalog.loading}>
          <RefreshCw size={15} />
          刷新环境目录
        </button>
      </header>
      {mutations.error && <ErrorNotice error={mutations.error} />}
      {selectionError && <ErrorNotice error={selectionError} />}
      <RecoveryNotice mutations={mutations} />
      {data?.active_operation && activeEnvironmentOperation(data.active_operation) && (
        <div className="info-banner">
          后台环境操作正在运行，新的安装与目录变更暂时锁定；离开页面不会取消。
          <button type="button" onClick={() => workspace.choose(data.active_operation!.id)}>
            查看当前环境操作
          </button>
        </div>
      )}
      {catalog.error && (
        <ErrorNotice
          error={
            catalog.error instanceof ApiError && catalog.error.status === 404
              ? new Error(
                  '当前后端尚未提供环境管理接口（HTTP 404）。请由运营方启用匹配契约的服务；下方运行诊断仍可查看，不展示演示组件。',
                )
              : catalog.error
          }
          onRetry={catalog.reload}
        />
      )}
      {catalog.loading && !data ? (
        <Loading label="正在读取真实环境组件目录…" />
      ) : (
        data && (
          <>
            {!data.settings.enabled && (
              <output className="info-banner">
                {data.settings.reason ?? '服务端未启用环境管理；网页不会执行替代安装。'}
              </output>
            )}
            <div className="environment-overview">
              <InstallLocation
                settings={data.settings}
                disabled={disabled}
                onSave={mutations.save}
              />
              <RecommendedBundles
                presets={data.presets}
                components={data.components}
                disabled={disabled}
                onInspect={(ids) => void mutations.start('inspect', ids, data.settings.revision)}
                onInstall={install}
              />
            </div>
            <div className="environment-detection">
              <span className="muted">
                最近检测：{data.checked_at ? dateText(data.checked_at) : '尚未检测'} ·
                不自动安装缺失组件
              </span>
              <button
                type="button"
                disabled={disabled || !data.components.length}
                onClick={() =>
                  void mutations.start(
                    'inspect',
                    data.components.map((item) => item.id),
                    data.settings.revision,
                  )
                }
              >
                <ScanLine size={15} />
                检测全部组件
              </button>
            </div>
            <ComponentLibrary
              components={data.components}
              disabled={disabled}
              onInstall={install}
              onInspect={(ids) => void mutations.start('inspect', ids, data.settings.revision)}
            />
          </>
        )
      )}
      {workspace.operation.error && (
        <ErrorNotice error={workspace.operation.error} onRetry={workspace.operation.reload} />
      )}
      <EnvironmentOperations
        selected={workspace.selected}
        selectionId={workspace.selectionId}
        loading={workspace.operation.loading}
        catalogAvailable={data !== null}
        operations={data?.operations ?? []}
        busy={mutations.busy || Boolean(mutations.pending) || mutations.storageError}
        readError={workspace.operation.error !== null}
        onSelect={workspace.choose}
        onCancel={mutations.cancel}
        onReload={workspace.operation.reload}
      />
      <RuntimeDiagnostics resource={workspace.runtime} />
      <footer className="environment-footer">
        <span>
          {product.name} · v{product.version}
        </span>
        <details className="environment-safety-note">
          <summary>运行与安装说明</summary>
          <p>
            在批准的 E 盘目录管理审核的 CPU
            运行时与模型。组件、检查和进度均从本机服务读取；只有明确确认后才会安装。
          </p>
          <p>本地 CPU · 无 GPU / 付费资源 · 正式 QA 保持独立</p>
        </details>
      </footer>
      {plan && data && (
        <InstallConfirmation
          plan={plan}
          currentRevision={data.settings.revision}
          planCurrent={planCurrent}
          busy={mutations.busy || catalog.loading}
          onClose={() => setPlan(null)}
          onConfirm={async () => {
            if (disabled || !planCurrent) return;
            await mutations.start(
              'install',
              plan.components.map((item) => item.id),
              plan.settings.revision,
            );
            setPlan(null);
          }}
        />
      )}
    </section>
  );
}
