import { CheckCircle2, Download, Package, ScanLine } from 'lucide-react';
import type { EnvironmentComponent, EnvironmentComponentId } from '../../api/environmentTypes';
import {
  environmentBytes,
  environmentGroups,
  environmentStatusLabels,
  safeEnvironmentSource,
} from '../../model/environment';
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
  return (
    <section className="panel environment-card component-library" aria-label="环境组件库">
      <header className="environment-section-header">
        <div>
          <h2>组件库</h2>
          <p className="muted">版本、状态与检查来自服务端；安装完成不能代替真实验证。</p>
        </div>
      </header>
      {!components.length ? (
        <p className="info-banner">服务端尚未提供组件目录；不会展示演示环境。</p>
      ) : (
        Object.entries(environmentGroups).map(([group, label]) => {
          const items = components.filter((item) => item.group === group);
          return items.length ? (
            <section className="component-group" key={group}>
              <h3>
                {label}
                <small>{items.length} 项</small>
              </h3>
              {items.map((component) => (
                <article
                  key={component.id}
                  className="environment-component"
                  data-component={component.id}
                >
                  <span className="environment-component-icon">
                    {component.status === 'ready' ? (
                      <CheckCircle2 size={20} />
                    ) : (
                      <Package size={20} />
                    )}
                  </span>
                  <div className="environment-component-body">
                    <div className="component-title">
                      <h4>{component.name}</h4>
                      <span className={`badge environment-status-${component.status}`}>
                        {environmentStatusLabels[component.status]}
                      </span>
                      {component.required && <small className="muted">核心组件</small>}
                    </div>
                    <p className="muted">{component.description}</p>
                    <dl className="component-metadata">
                      <div>
                        <dt>目标版本</dt>
                        <dd>{component.version}</dd>
                      </div>
                      <div>
                        <dt>检测版本</dt>
                        <dd>{component.detected_version ?? '未报告'}</dd>
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
                    {component.location && (
                      <p className="component-location break-word">位置：{component.location}</p>
                    )}
                    {component.dependencies.length > 0 && (
                      <p className="muted">
                        前置依赖：
                        {component.dependencies
                          .map((id) => components.find((item) => item.id === id)?.name ?? id)
                          .join(' · ')}
                      </p>
                    )}
                    {component.problem && <p className="component-problem">{component.problem}</p>}
                    <details>
                      <summary>来源、许可证与检查依据</summary>
                      <p className="break-word">许可证：{component.license || '未报告'}</p>
                      {safeEnvironmentSource(component.source_url) ? (
                        <a
                          href={safeEnvironmentSource(component.source_url)!}
                          target="_blank"
                          rel="noreferrer"
                        >
                          服务端核定来源
                        </a>
                      ) : (
                        <p className="break-word">来源：{component.source_url || '未报告'}</p>
                      )}
                      {component.checks.length ? (
                        <ul>
                          {component.checks.map((check, index) => (
                            <li key={index}>
                              {check.ok ? '通过' : '未通过'} · {check.name}：{check.message}
                            </li>
                          ))}
                        </ul>
                      ) : (
                        <p className="muted">尚未报告检查结果。</p>
                      )}
                    </details>
                  </div>
                  <div className="component-actions">
                    <button
                      type="button"
                      aria-label={`检测 ${component.name}`}
                      disabled={disabled}
                      onClick={() => onInspect([component.id])}
                    >
                      <ScanLine size={14} />
                      检测
                    </button>
                    <button
                      type="button"
                      aria-label={`安装 ${component.name}`}
                      disabled={disabled || !component.installable}
                      onClick={() => onInstall([component.id])}
                      title={
                        !component.installable ? '服务端不允许安装此组件，请检查原因' : undefined
                      }
                    >
                      <Download size={14} />
                      安装
                    </button>
                  </div>
                </article>
              ))}
            </section>
          ) : null;
        })
      )}
    </section>
  );
}
