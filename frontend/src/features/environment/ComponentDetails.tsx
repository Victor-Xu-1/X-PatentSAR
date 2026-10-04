import type { EnvironmentComponent } from '../../api/environmentTypes';
import {
  environmentBytes,
  environmentStatusLabels,
  safeEnvironmentSource,
} from '../../model/environment';
import { dateText } from '../../model/presentation';

function ComponentChecks({ checks }: { checks: EnvironmentComponent['checks'] }) {
  return checks.length ? (
    <ul>
      {checks.map((check, index) => (
        <li key={index}>
          {check.ok ? '通过' : '未通过'} · {check.name}：{check.message}
        </li>
      ))}
    </ul>
  ) : (
    <p className="muted">尚未报告检查结果。</p>
  );
}

export function ComponentDetails({
  component,
  components,
}: {
  component: EnvironmentComponent;
  components: EnvironmentComponent[];
}) {
  const current = component.verification === 'current';
  const lastCheck = component.verification === 'stale' ? component.last_check : null;
  const source = safeEnvironmentSource(component.source_url);
  return (
    <details>
      <summary>版本、来源与检查</summary>
      <p className="muted">{component.description}</p>
      <dl className="component-metadata">
        <div>
          <dt>目标版本</dt>
          <dd>{component.version}</dd>
        </div>
        <div>
          <dt>当前实测版本</dt>
          <dd>{current ? (component.detected_version ?? '未报告') : '尚无当前检测'}</dd>
        </div>
        <div>
          <dt>下载</dt>
          <dd>{environmentBytes(component.download_bytes)}</dd>
        </div>
        <div>
          <dt>已占用</dt>
          <dd>{environmentBytes(component.installed_bytes)}</dd>
        </div>
      </dl>
      {component.dependencies.length > 0 && (
        <p className="muted">
          前置依赖：
          {component.dependencies
            .map((id) => components.find((item) => item.id === id)?.name ?? id)
            .join(' · ')}
        </p>
      )}
      <p className="break-word">许可证：{component.license || '未报告'}</p>
      {source ? (
        <a href={source} target="_blank" rel="noreferrer">
          服务端核定来源
        </a>
      ) : (
        <p className="break-word">来源：{component.source_url || '未报告'}</p>
      )}
      {current ? (
        <ComponentChecks checks={component.checks} />
      ) : (
        <p className="muted">尚无当前检查结果，请明确检测。</p>
      )}
      {lastCheck && (
        <section aria-label="上次检测结果">
          <p>上次检测（已过期） · {environmentStatusLabels[lastCheck.status]}</p>
          <p>上次实测版本：{lastCheck.detected_version ?? '未报告'}</p>
          <p>
            上次检测时间：
            {lastCheck.checked_at ? (
              <time dateTime={lastCheck.checked_at}>{dateText(lastCheck.checked_at)}</time>
            ) : (
              '时间未知'
            )}
          </p>
          {lastCheck.problem && <p className="component-problem">{lastCheck.problem}</p>}
          <ComponentChecks checks={lastCheck.checks} />
        </section>
      )}
    </details>
  );
}
