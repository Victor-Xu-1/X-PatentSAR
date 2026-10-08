import { useTranslation } from '../../i18n';
import { useId, useState } from 'react';
import { Dialog } from '../../components/Dialog';
import type {
  EnvironmentComponent,
  EnvironmentComponentId,
  EnvironmentSettings,
} from '../../api/environmentTypes';
import { environmentBytes, environmentComponentName } from '../../model/environment';
import {
  environmentComponentBadge,
  isEnvironmentComponentReady,
} from '../../model/environmentStatus';
export interface InstallPlan {
  scope: 'complete' | 'components';
  components: EnvironmentComponent[];
  settings: EnvironmentSettings;
  requested: EnvironmentComponentId[];
}
export function InstallConfirmation({
  plan,
  currentRevision,
  planCurrent,
  busy,
  onClose,
  onConfirm,
}: {
  plan: InstallPlan;
  currentRevision: number;
  planCurrent: boolean;
  busy: boolean;
  onClose: () => void;
  onConfirm: () => Promise<void>;
}) {
  const { t } = useTranslation();
  const [confirmed, setConfirmed] = useState(false);
  const reasonId = useId();
  const configurationChanged = currentRevision !== plan.settings.revision;
  const stale = configurationChanged || !planCurrent;
  const missingLicense = plan.components.some((component) => !component.license.trim());
  const showProblem = !busy && (stale || missingLicense);
  return (
    <Dialog
      title={plan.scope === 'complete' ? t('确认完整环境部署') : t('确认环境安装')}
      onClose={onClose}
      busy={busy}
      wide
      className="environment-install-dialog"
    >
      <div className="dialog-body environment-installation">
        <div className="installation-destination">
          <span className="muted">{t('安装位置')}</span>
          <strong className="break-word">{plan.settings.install_root}</strong>
        </div>
        <p>
          {t('一次后台操作配置以下 CPU 组件，不安装 GPU / CUDA、不调用付费服务、不覆盖未知环境。')}
        </p>
        <p className="muted">
          {plan.scope === 'complete'
            ? t(
                '包含完整运行环境及全部前置依赖。后端逐项复检并复用合格环境，仅安装缺失或不合格组件；检测错误会停止，不以重装掩盖。',
              )
            : t('包含所选组件及全部前置依赖；后端复检并复用合格环境。')}
        </p>
        <p className="muted">
          {t(
            '下载按服务端报告展示，未报告不视为零，复用可减少下载。全部验证通过才应用配置，不改变已有任务或专利结果。',
          )}
        </p>
        <ul className="installation-plan" aria-label={t('环境安装计划')}>
          {plan.components.map((component) => (
            <li key={component.id} data-install-component={component.id}>
              <div className="installation-component-heading">
                <strong>{environmentComponentName(component)}</strong>
                <span
                  className={`badge environment-status-${environmentComponentBadge(component).tone}`}
                >
                  {isEnvironmentComponentReady(component)
                    ? t('已安装·已验证；后端复验后复用')
                    : environmentComponentBadge(component).label}
                </span>
              </div>
              <small>
                {t('目标版本 {version} · {role}', {
                  version: component.version,
                  role: t(plan.requested.includes(component.id) ? '所选组件' : '前置依赖'),
                })}
              </small>
              <span className="installation-license">
                {t('下载：{size} · 许可证：{license}', {
                  size: environmentBytes(component.download_bytes),
                  license: component.license || t('未报告'),
                })}
              </span>
              <details className="installation-source-details">
                <summary>{t('来源与位置')}</summary>
                <p className="break-word">
                  {t('来源：{source}', { source: component.source_url || t('未报告') })}
                </p>
                {component.location && (
                  <p className="break-word">
                    {t('现有位置：{location}', { location: component.location })}
                  </p>
                )}
              </details>
            </li>
          ))}
        </ul>
        {showProblem && (
          <p id={reasonId} className="error-notice" role="alert">
            {stale
              ? configurationChanged
                ? t('安装目录配置已变化，请关闭并重新确认。')
                : t('组件状态或依赖计划已变化，请关闭并重新确认；不重复安装已有组件。')
              : t('服务端未提供完整许可证信息，不能确认安装。')}
          </p>
        )}
        <label className="option-check">
          <input
            data-initial-focus
            type="checkbox"
            aria-describedby={showProblem ? reasonId : undefined}
            checked={confirmed}
            onChange={(e) => setConfirmed(e.target.checked)}
            disabled={busy || stale || missingLicense}
          />
          {t('我已确认安装目录、CPU 下载范围及上述许可证')}
        </label>
        <footer className="dialog-actions">
          <button type="button" disabled={busy} onClick={onClose}>
            {t('取消')}
          </button>
          <button
            type="button"
            className="primary"
            disabled={!confirmed || busy || stale || missingLicense}
            onClick={() => void onConfirm()}
          >
            {busy ? t('正在提交后台操作…') : t('确认下载并安装')}
          </button>
        </footer>
      </div>
    </Dialog>
  );
}
