import { Filter, Search } from 'lucide-react';
import type { Filters } from '../../api/types';
import { confidenceLabels, reviewLabels } from '../../model/presentation';
export function ResultFilters({
  filters,
  targets,
  onChange,
  total,
  disabled,
}: {
  filters: Filters;
  targets: string[];
  onChange: (patch: Partial<Filters>) => void;
  total: number | null;
  disabled: boolean;
}) {
  return (
    <div className="result-filters">
      <div className="results-heading">
        <h2>化合物–活性数据{total !== null && <span>（{total}）</span>}</h2>
        <span className="muted">
          <Filter size={13} />
          按证据筛选
        </span>
      </div>
      <div className="filter-controls">
        <label className="search-field">
          <Search size={15} />
          <input
            aria-label="搜索结果"
            data-dialog-focus-fallback
            value={filters.q}
            placeholder="搜索编号、靶点或关键词…"
            disabled={disabled}
            onChange={(e) => onChange({ q: e.target.value, page: 1 })}
          />
        </label>
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
      </div>
    </div>
  );
}
