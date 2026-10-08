import { useTranslation } from '../../i18n';
import { CheckCircle2, Download, Package, ScanLine } from 'lucide-react';
import type { EnvironmentComponent, EnvironmentComponentId } from '../../api/environmentTypes';
import { environmentComponentName, environmentGroups } from '../../model/environment';
import {
  environmentComponentAction,
  environmentComponentBadge,
  hasEnvironmentComponentFailure,
  isEnvironmentComponentReady,
} from '../../model/environmentStatus';
import { dateText } from '../../model/presentation';
import { ComponentDetails } from './ComponentDetails';
export function ComponentLibrary({
  components,
  disabled,
  onInspect,
  onInstall,
}: {
  components: EnvironmentComponent[];
  disabled: boolean;
  onInspect: (ids: EnvironmentComponentId[]) => void;
  onInstall: (ids: EnvironmentComponentId[]) => void;
}) {
  const { t } = useTranslation();
  return (
    <section className="panel environment-card component-library" aria-label={t('环境组件库')}>
      <header className="environment-section-header">
        <div>
          <h2>{t('组件库')}</h2>
        </div>
      </header>
      {!components.length ? (
        <p className="info-banner">{t('服务端尚未提供组件目录；不会展示演示环境。')}</p>
      ) : (
        Object.entries(environmentGroups).map(([group, label]) => {
          const items = components.filter((item) => item.group === group);
          return items.length ? (
            <section className="component-group" key={group}>
              <h3>
                {t(label)}
                <small>{t('{count} 项', { count: items.length })}</small>
              </h3>
              {items.map((component) => {
                const name = environmentComponentName(component);
                const badge = environmentComponentBadge(component);
                const action = environmentComponentAction(component);
                const actionLabel = {
                  installed: t('已安装'),
                  inspect: t('先检测'),
                  install: t('安装'),
                  repair: t('修复'),
                }[action];
                const canInstall =
                  (action === 'install' || action === 'repair') && component.installable;
                const current = component.verification === 'current';
                const checkedAt = current
                  ? component.checked_at
                  : component.verification === 'stale'
                    ? component.last_check?.checked_at
                    : null;
                const problem =
                  current ||
                  hasEnvironmentComponentFailure(component) ||
                  component.presence === 'missing' ||
                  component.presence === 'unconfigured'
                    ? component.problem
                    : null;
                return (
                  <article
                    key={component.id}
                    className="environment-component"
                    data-component={component.id}
                  >
                    <span className="environment-component-icon">
                      {isEnvironmentComponentReady(component) ? (
                        <CheckCircle2 size={20} />
                      ) : (
                        <Package size={20} />
                      )}
                    </span>
                    <div className="environment-component-body">
                      <div className="component-title">
                        <h4>{name}</h4>
                        <span className={`badge environment-status-${badge.tone}`}>
                          {badge.label}
                        </span>
                        <small className="muted">
                          {t('目标：{version}', { version: component.version })}
                        </small>
                        {current && (
                          <small className="muted">
                            {t('实测：{version}', {
                              version: component.detected_version ?? t('未报告'),
                            })}
                          </small>
                        )}
                      </div>
                      <p
                        className="component-location break-word"
                        title={component.location ?? undefined}
                      >
                        {t('位置：{location}', { location: component.location ?? t('未配置') })}
                      </p>
                      <p className="component-checked-at muted">
                        {component.verification === 'stale' ? t('上次检测时间：') : t('检测时间：')}
                        {checkedAt ? (
                          <time dateTime={checkedAt}>{dateText(checkedAt)}</time>
                        ) : component.verification === 'unchecked' ? (
                          t('未知（待检测）')
                        ) : (
                          t('时间未知')
                        )}
                      </p>
                      {problem && <p className="component-problem">{problem}</p>}
                      <ComponentDetails component={component} components={components} />
                    </div>
                    <div className="component-actions">
                      <button
                        type="button"
                        aria-label={t('检测 {name}', { name })}
                        disabled={disabled}
                        onClick={() => onInspect([component.id])}
                      >
                        <ScanLine size={14} />
                        {t('检测')}
                      </button>
                      <button
                        type="button"
                        aria-label={t('{action} {name}', { action: actionLabel, name })}
                        disabled={disabled || !canInstall}
                        onClick={() => onInstall([component.id])}
                        title={
                          action === 'installed'
                            ? t('已通过当前检测，无需重复安装')
                            : action === 'inspect'
                              ? t('先检测组件状态，不重复安装已有组件')
                              : !component.installable
                                ? t('服务端不允许安装此组件，请检查原因')
                                : action === 'repair'
                                  ? t('修复仍需确认完整依赖、下载范围及许可证')
                                  : undefined
                        }
                      >
                        <Download size={14} />
                        {actionLabel}
                      </button>
                    </div>
                  </article>
                );
              })}
            </section>
          ) : null;
        })
      )}
    </section>
  );
}
