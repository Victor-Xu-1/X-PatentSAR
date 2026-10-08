import { useTranslation } from '../../i18n';
import type { EnvironmentComponent } from '../../api/environmentTypes';
import {
  environmentBytes,
  environmentComponentDescription,
  environmentComponentName,
  environmentStatusLabels,
  safeEnvironmentSource,
} from '../../model/environment';
import { dateText } from '../../model/presentation';

function ComponentChecks({ checks }: { checks: EnvironmentComponent['checks'] }) {
  const { t } = useTranslation();
  return checks.length ? (
    <ul>
      {checks.map((check, index) => (
        <li key={index}>
          {check.ok ? t('通过') : t('未通过')} · {check.name}：{check.message}
        </li>
      ))}
    </ul>
  ) : (
    <p className="muted">{t('尚未报告检查结果。')}</p>
  );
}

export function ComponentDetails({
  component,
  components,
}: {
  component: EnvironmentComponent;
  components: EnvironmentComponent[];
}) {
  const { t } = useTranslation();
  const current = component.verification === 'current';
  const lastCheck = component.verification === 'stale' ? component.last_check : null;
  const source = safeEnvironmentSource(component.source_url);
  return (
    <details>
      <summary>{t('版本、来源与检查')}</summary>
      <p className="muted">{environmentComponentDescription(component)}</p>
      <dl className="component-metadata">
        <div>
          <dt>{t('目标版本')}</dt>
          <dd>{component.version}</dd>
        </div>
        <div>
          <dt>{t('当前实测版本')}</dt>
          <dd>{current ? (component.detected_version ?? t('未报告')) : t('尚无当前检测')}</dd>
        </div>
        <div>
          <dt>{t('下载')}</dt>
          <dd>{environmentBytes(component.download_bytes)}</dd>
        </div>
        <div>
          <dt>{t('已占用')}</dt>
          <dd>{environmentBytes(component.installed_bytes)}</dd>
        </div>
      </dl>
      {component.dependencies.length > 0 && (
        <p className="muted">
          {t('前置依赖：')}
          {component.dependencies
            .map((id) => {
              const dependency = components.find((item) => item.id === id);
              return dependency ? environmentComponentName(dependency) : id;
            })
            .join(' · ')}
        </p>
      )}
      <p className="break-word">
        {t('许可证：')}
        {component.license || t('未报告')}
      </p>
      {source ? (
        <a href={source} target="_blank" rel="noreferrer">
          {t('服务端核定来源')}
        </a>
      ) : (
        <p className="break-word">
          {t('来源：')}
          {component.source_url || t('未报告')}
        </p>
      )}
      {current ? (
        <ComponentChecks checks={component.checks} />
      ) : (
        <p className="muted">{t('尚无当前检查结果，请明确检测。')}</p>
      )}
      {lastCheck && (
        <section aria-label={t('上次检测结果')}>
          <p>
            {t('上次检测（已过期） · {status}', {
              status: t(environmentStatusLabels[lastCheck.status]),
            })}
          </p>
          <p>
            {t('上次实测版本：')}
            {lastCheck.detected_version ?? t('未报告')}
          </p>
          <p>
            {t('上次检测时间：')}
            {lastCheck.checked_at ? (
              <time dateTime={lastCheck.checked_at}>{dateText(lastCheck.checked_at)}</time>
            ) : (
              t('时间未知')
            )}
          </p>
          {lastCheck.problem && <p className="component-problem">{lastCheck.problem}</p>}
          <ComponentChecks checks={lastCheck.checks} />
        </section>
      )}
    </details>
  );
}
