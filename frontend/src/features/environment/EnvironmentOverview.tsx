import { errorText, useTranslation } from '../../i18n';
import { CircleCheck, CircleHelp, Download, ScanLine } from 'lucide-react';
import type { EnvironmentCatalog, EnvironmentComponentId } from '../../api/environmentTypes';
import { canSetupEnvironmentPlan, environmentSetupComponents } from '../../model/environmentSetup';
import {
  environmentComponentAction,
  environmentReadiness,
  isEnvironmentComponentReady,
} from '../../model/environmentStatus';

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
  const { t } = useTranslation();
  let plan = null;
  let problem: string | null = null;
  try {
    plan = environmentSetupComponents(catalog);
  } catch (error) {
    problem = error instanceof Error ? errorText(error) : t('完整部署计划无效。');
  }
  const counts = environmentReadiness(catalog.components);
  const ready = plan !== null && plan.every(isEnvironmentComponentReady);
  const setupPossible = plan !== null && canSetupEnvironmentPlan(plan);
  const preferInspect =
    !setupPossible ||
    plan?.some((component) => environmentComponentAction(component) === 'inspect');
  return (
    <section className="environment-card environment-overview" aria-label={t('完整运行环境')}>
      <div className="environment-section-header">
        <div className="environment-overview-state">
          <span
            className={`environment-overview-icon${ready ? ' is-ready' : ''}`}
            aria-hidden="true"
          >
            {ready ? <CircleCheck size={26} /> : <CircleHelp size={26} />}
          </span>
          <div className="environment-overview-heading">
            <h2>{t('完整运行环境')}</h2>
            <output className="muted" aria-label={t('环境就绪状态')} aria-live="polite">
              {counts.provided > 0 && counts.needsCheck === counts.provided
                ? t('需要检测 · {count} 个组件', { count: counts.needsCheck })
                : t('已就绪 {ready}/{total}', counts)}
              {counts.needsCheck > 0 &&
                counts.needsCheck < counts.provided &&
                t(' · {count} 待检测', { count: counts.needsCheck })}
            </output>
          </div>
        </div>
        <div className="environment-overview-actions">
          <button
            type="button"
            className={setupPossible && !preferInspect ? 'primary' : undefined}
            disabled={disabled || !setupPossible}
            onClick={onSetup}
          >
            <Download size={15} />
            {ready ? t('环境已就绪') : t('一键部署全部环境')}
          </button>
          <button
            type="button"
            className={preferInspect ? 'primary' : undefined}
            disabled={disabled || !catalog.components.length}
            onClick={() =>
              onInspect(
                plan?.map((component) => component.id) ??
                  catalog.components.map((component) => component.id),
              )
            }
          >
            <ScanLine size={15} />
            {ready ? t('重新检测') : t('检测全部组件')}
          </button>
        </div>
      </div>
      <div className="environment-overview-footer">
        <p className="muted">{t('PDF 提取 · 结构识别 · 六项指标')}</p>
        <button type="button" className="environment-details-trigger" onClick={onDetails}>
          {t('环境详情')}
        </button>
      </div>
      {problem && <p className="info-banner">{problem}</p>}
      {plan !== null && !ready && !canSetupEnvironmentPlan(plan) && (
        <p className="info-banner">
          {t('完整部署暂不可用，请查看组件详情中的服务端限制或检测状态。')}
        </p>
      )}
      {!catalog.components.length && (
        <p className="info-banner">{t('服务端尚未提供组件目录；不会展示演示环境。')}</p>
      )}
    </section>
  );
}
