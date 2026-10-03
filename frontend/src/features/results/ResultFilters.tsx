import type { Filters } from '../../api/types';
import { confidenceLabels, reviewLabels } from '../../model/presentation';
export function ResultFilters({
  filters,
  targets,
  onChange,
  disabled,
}: {
  filters: Filters;
  targets: string[];
  onChange: (patch: Partial<Filters>) => void;
  disabled: boolean;
}) {
  return (
    <div className="result-filters">
      <div className="filter-controls">
        <label>
          靶点
          <select
            aria-label="筛选靶点"
            value={filters.target}
            disabled={disabled}
            onChange={(e) => onChange({ target: e.target.value, page: 1 })}
          >
            <option value="">全部靶点</option>
            {targets.map((target) => (
              <option key={target}>{target}</option>
            ))}
          </select>
        </label>
        <label>
          绑定证据
          <select
            aria-label="筛选绑定证据"
            value={filters.confidence}
            disabled={disabled}
            onChange={(e) => onChange({ confidence: e.target.value, page: 1 })}
          >
            <option value="">全部绑定证据</option>
            {Object.entries(confidenceLabels).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label>
          复核状态
          <select
            aria-label="筛选复核状态"
            value={filters.review}
            disabled={disabled}
            onChange={(e) => onChange({ review: e.target.value, page: 1 })}
          >
            <option value="">全部复核状态</option>
            {Object.entries(reviewLabels).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
      </div>
      <button
        type="button"
        disabled={disabled}
        onClick={() => onChange({ target: '', confidence: '', review: '', page: 1 })}
      >
        重置筛选
      </button>
    </div>
  );
}
