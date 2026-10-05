import { RefreshCw } from 'lucide-react';
import { useState } from 'react';
import type { Identity } from '../../api/types';
import { ApiError } from '../../api/errors';
import { activeEnvironmentOperation } from '../../model/environment';
import { ErrorNotice, Loading } from '../../components/Feedback';
import { useEnvironmentWorkspace } from './useEnvironmentWorkspace';
import { EnvironmentOverview } from './EnvironmentOverview';
import { EnvironmentDetails } from './EnvironmentDetails';
import { InstallConfirmation } from './InstallConfirmation';
import { useEnvironmentInstallPlan } from './useEnvironmentInstallPlan';
import { RecoveryNotice } from './RecoveryNotice';
import { EnvironmentProgress } from './EnvironmentProgress';

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
  const [detailsOpen, setDetailsOpen] = useState(false);
  const blocked =
    mutations.busy ||
    Boolean(mutations.pending) ||
    mutations.storageError ||
    activeEnvironmentOperation(data?.active_operation ?? null) ||
    activeEnvironmentOperation(workspace.selected);
  const disabled = blocked || !data?.settings.enabled || catalog.loading;
  const installation = useEnvironmentInstallPlan(data, disabled);
  const { plan } = installation;
  return (
    <section className="management-page environment-page" aria-label={`${product.name} 环境管理`}>
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
      {installation.error && <ErrorNotice error={installation.error} />}
      <RecoveryNotice mutations={mutations} />
      {catalog.error && (
        <ErrorNotice
          error={
            catalog.error instanceof ApiError && catalog.error.status === 404
              ? new Error('当前后端未提供环境管理，请更新后端后重试。')
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
            <EnvironmentOverview
              catalog={data}
              disabled={disabled}
              onSetup={installation.setup}
              onInspect={(ids) => void mutations.start('inspect', ids, data.settings.revision)}
              onDetails={() => setDetailsOpen(true)}
            />
          </>
        )
      )}
      {workspace.operation.error && (
        <ErrorNotice error={workspace.operation.error} onRetry={workspace.operation.reload} />
      )}
      <EnvironmentProgress
        selected={workspace.selected}
        selectionId={workspace.selectionId}
        loading={workspace.operation.loading}
        busy={mutations.busy || Boolean(mutations.pending) || mutations.storageError}
        readError={workspace.operation.error !== null}
        onCancel={mutations.cancel}
        onReload={workspace.operation.reload}
      />
      {data && detailsOpen && (
        <EnvironmentDetails
          catalog={data}
          disabled={disabled}
          onClose={() => setDetailsOpen(false)}
          onSave={mutations.save}
          onInspect={(ids) => void mutations.start('inspect', ids, data.settings.revision)}
          onInstall={(ids) => {
            setDetailsOpen(false);
            installation.install(ids);
          }}
        />
      )}
      {plan && data && (
        <InstallConfirmation
          plan={plan}
          currentRevision={data.settings.revision}
          planCurrent={installation.current}
          busy={mutations.busy || catalog.loading}
          onClose={installation.close}
          onConfirm={async () => {
            if (disabled || !installation.current) return;
            await mutations.start(
              'install',
              plan.components.map((item) => item.id),
              plan.settings.revision,
            );
            installation.close();
          }}
        />
      )}
    </section>
  );
}
