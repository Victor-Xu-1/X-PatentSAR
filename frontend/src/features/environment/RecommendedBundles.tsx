import { Download, ScanLine } from 'lucide-react';
import type {
  EnvironmentComponent,
  EnvironmentComponentId,
  EnvironmentPreset,
} from '../../api/environmentTypes';
import { selectedEnvironmentComponents } from '../../model/environment';
import { canInstallEnvironmentPlan, environmentBundleAction } from '../../model/environmentStatus';
export function RecommendedBundles({
  presets,
  components,
  disabled,
  onInspect,
  onInstall,
}: {
  presets: EnvironmentPreset[];
  components: EnvironmentComponent[];
  disabled: boolean;
  onInspect: (ids: EnvironmentComponentId[]) => void;
  onInstall: (ids: EnvironmentComponentId[]) => void;
}) {
  return (
    <section className="panel environment-card recommended-card">
      <h2>推荐组合</h2>
      <p className="muted">使用服务端审核的组件组合，不添加任意软件包或额外服务。</p>
      {presets.length ? (
        presets.map((preset) => {
          let plan: EnvironmentComponent[] = [];
          let problem: string | null = null;
          try {
            plan = selectedEnvironmentComponents(components, preset.component_ids);
          } catch (error) {
            problem = error instanceof Error ? error.message : '组件依赖目录无效。';
          }
          const action = environmentBundleAction(plan);
          const label = { ready: '已就绪', inspect: '检测组合', install: '安装组合' }[action];
          const complete =
            problem === null && (action === 'inspect' || canInstallEnvironmentPlan(plan));
          return (
            <article className="environment-preset" key={preset.id}>
              <div>
                <h3>{preset.name}</h3>
                <p className="muted">{preset.description}</p>
                <p className="preset-components">
                  计划组件（含前置依赖）：{plan.map((item) => item.name).join(' · ')}
                </p>
                {problem && <p className="component-problem">{problem}</p>}
              </div>
              <button
                type="button"
                className="primary"
                disabled={disabled || !complete}
                aria-label={`${label} ${preset.name}`}
                onClick={() =>
                  action === 'inspect'
                    ? onInspect(plan.map((component) => component.id))
                    : onInstall(preset.component_ids)
                }
              >
                {action === 'inspect' ? <ScanLine size={14} /> : <Download size={14} />}
                {label}
              </button>
            </article>
          );
        })
      ) : (
        <p className="info-banner">服务端尚未提供推荐组合。</p>
      )}
    </section>
  );
}
