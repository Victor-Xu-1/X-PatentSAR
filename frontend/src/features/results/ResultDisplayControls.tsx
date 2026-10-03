import type { ResultDensity } from '../../model/results';

export function ResultDisplayControls({
  metrics,
  visibleMetrics,
  density,
  onDensity,
  onMetrics,
  disabled,
}: {
  metrics: string[];
  visibleMetrics: string[];
  density: ResultDensity;
  onDensity: (value: ResultDensity) => void;
  onMetrics: (value: string[] | null) => void;
  disabled: boolean;
}) {
  return (
    <div className="result-display-controls">
      <fieldset className="density-controls">
        <legend className="sr-only">结果表格密度</legend>
        {(['compact', 'comfortable'] as const).map((value) => (
          <button
            key={value}
            type="button"
            aria-pressed={density === value}
            disabled={disabled}
            onClick={() => onDensity(value)}
          >
            {value === 'compact' ? '紧凑视图' : '舒适视图'}
          </button>
        ))}
      </fieldset>
      <fieldset className="metric-options" disabled={disabled}>
        <legend>
          活性指标（{visibleMetrics.length} / {metrics.length}）
        </legend>
        <button type="button" onClick={() => onMetrics(null)}>
          显示全部指标
        </button>
        {metrics.map((metric) => (
          <label key={metric}>
            <input
              type="checkbox"
              aria-label={`显示指标 ${metric}`}
              checked={visibleMetrics.includes(metric)}
              onChange={(event) =>
                onMetrics(
                  event.target.checked
                    ? [...visibleMetrics, metric]
                    : visibleMetrics.filter((name) => name !== metric),
                )
              }
            />
            <span>{metric || '未命名指标'}</span>
          </label>
        ))}
        {!metrics.length && <span className="muted">尚无可用指标</span>}
      </fieldset>
    </div>
  );
}
