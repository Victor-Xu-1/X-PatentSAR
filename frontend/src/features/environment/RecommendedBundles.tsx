import { Download } from 'lucide-react';
import type {
  EnvironmentComponent,
  EnvironmentComponentId,
  EnvironmentPreset,
} from '../../api/environmentTypes';
import { selectedEnvironmentComponents } from '../../model/environment';
export function RecommendedBundles({
  presets,
  components,
  disabled,
  onInstall,
}: {
  presets: EnvironmentPreset[];
  components: EnvironmentComponent[];
  disabled: boolean;
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
          const complete = problem === null && plan.every((item) => item.installable);
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
                aria-label={`安装组合 ${preset.name}`}
                onClick={() => onInstall(preset.component_ids)}
              >
                <Download size={14} />
                安装组合
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
