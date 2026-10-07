import { CircleCheck, CircleHelp, Download, ScanLine } from 'lucide-react';
import type { EnvironmentCatalog, EnvironmentComponentId } from '../../api/environmentTypes';
import { environmentComponentIds } from '../../api/environmentTypes';
import { canSetupEnvironmentPlan, environmentSetupComponents } from '../../model/environmentSetup';
import { isEnvironmentComponentReady } from '../../model/environmentStatus';

export function EnvironmentOverview({
  catalog,
  disabled,
  onSetup,
  onInspect,
  onDetails,
}: {
  catalog: EnvironmentCatalog;
  disabled: boolean;
  onSetup: () => void;
  onInspect: (ids: EnvironmentComponentId[]) => void;
  onDetails: () => void;
}) {
  let plan = null;
  let problem: string | null = null;
  try {
    plan = environmentSetupComponents(catalog);
  } catch (error) {
    problem = error instanceof Error ? error.message : '完整部署计划无效。';
  }
  const readyCount = catalog.components.filter(isEnvironmentComponentReady).length;
  const ready = plan !== null && plan.every(isEnvironmentComponentReady);
  return (
    <section className="environment-card environment-overview" aria-label="完整运行环境">
      <div className="environment-section-header">
        <div className="environment-overview-state">
          <span
            className={`environment-overview-icon${ready ? ' is-ready' : ''}`}
            aria-hidden="true"
          >
            {ready ? <CircleCheck size={26} /> : <CircleHelp size={26} />}
          </span>
          <div className="environment-overview-heading">
            <h2>完整运行环境</h2>
            <span className="muted">
              已就绪 {readyCount}/{environmentComponentIds.length}
            </span>
          </div>
        </div>
        <div className="environment-overview-actions">
          <button
            type="button"
            className="primary"
            disabled={disabled || plan === null || !canSetupEnvironmentPlan(plan)}
            onClick={onSetup}
          >
            <Download size={15} />
            {ready ? '环境已就绪' : '一键部署全部环境'}
          </button>
          <button
            type="button"
            disabled={disabled || !catalog.components.length}
            onClick={() =>
              onInspect(
                plan?.map((component) => component.id) ??
                  catalog.components.map((component) => component.id),
              )
            }
          >
            <ScanLine size={15} />
            {ready ? '重新检测' : '检测全部组件'}
          </button>
        </div>
      </div>
      <p className="muted">PDF 提取 · 结构识别 · 六项指标</p>
      {problem && <p className="info-banner">{problem}</p>}
      {plan !== null && !ready && !canSetupEnvironmentPlan(plan) && (
        <p className="info-banner">完整部署暂不可用，请查看组件详情中的服务端限制或检测状态。</p>
      )}
      <button type="button" className="environment-details-trigger" onClick={onDetails}>
        存储位置
      </button>
      {!catalog.components.length && (
        <p className="info-banner">服务端尚未提供组件目录；不会展示演示环境。</p>
      )}
    </section>
  );
}
