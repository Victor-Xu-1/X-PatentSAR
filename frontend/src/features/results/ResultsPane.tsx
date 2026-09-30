import { Download } from 'lucide-react';
import type { Compound, Filters, Project, Results } from '../../api/types';
import type { Resource } from '../../hooks/useResource';
import { Empty, ErrorNotice, Loading } from '../../components/Feedback';
import { Metrics } from './Metrics';
import { ResultFilters } from './ResultFilters';
import { ResultsTable } from './ResultsTable';
import { Pagination } from './Pagination';
import { acceptanceLabels } from '../../model/presentation';

export function ResultsPane({
  project,
  resource,
  filters,
  metric,
  selected,
  focusedId,
  onMetric,
  onFilters,
  onSelect,
  onSelectPage,
  onJump,
  onCrop,
  onReview,
  onExport,
  onUpload,
}: {
  project: Project | null;
  resource: Resource<Results>;
  filters: Filters;
  metric: string;
  selected: Set<string>;
  focusedId: string | null;
  onMetric: (metric: string) => void;
  onFilters: (patch: Partial<Filters>) => void;
  onSelect: (id: string) => void;
  onSelectPage: (checked: boolean) => void;
  onJump: (row: Compound) => void;
  onCrop: (row: Compound) => void;
  onReview: (row: Compound) => void;
  onExport: () => void;
  onUpload: () => void;
}) {
  const result = resource.data;
  return (
    <div className="result-data-view">
      <Metrics project={project} />
      {project && (
        <div className={`acceptance-banner ${project.acceptance.state}`}>
          <span>{acceptanceLabels[project.acceptance.state]}</span>
          <small>
            {project.is_historical
              ? '来源：历史运行导入；旧契约证据不视为当前高置信结果。'
              : '正式验收仅由确定性 QA 决定，人工注记不改变验收。'}
          </small>
          {project.acceptance.errors.length > 0 && (
            <details>
              <summary>查看核心验收问题（{project.acceptance.errors.length}）</summary>
              <ul>
                {project.acceptance.errors.map((error, index) => (
                  <li key={index}>{error}</li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}
      <ResultFilters
        filters={filters}
        metrics={result?.metrics ?? []}
        targets={result?.targets ?? []}
        metric={metric}
        onMetric={onMetric}
        onChange={onFilters}
        total={result?.total ?? null}
        disabled={!project}
      />
      <div className="selection-bar">
        <span>
          {selected.size
            ? `已选择 ${selected.size} 个化合物（跨页保留）`
            : '点击结构查看裁图 · 点击来源返回原文'}
        </span>
        <button type="button" onClick={onExport} disabled={!project || !result?.total}>
          <Download size={14} />
          {selected.size ? `导出所选 (${selected.size})` : '导出结果'}
        </button>
      </div>
      <div className="results-content" aria-busy={resource.loading}>
        {resource.error ? (
          <ErrorNotice error={resource.error} onRetry={resource.reload} />
        ) : resource.loading && !result ? (
          <Loading label="正在查询真实结构与活性结果…" />
        ) : !project ? (
          <Empty
            title="开始探索专利中的结构与活性"
            description="上传一份原始专利 PDF，或从项目列表打开已有结果。所有结构、指标和来源均来自真实提取，不生成演示数据。"
            action={
              <button type="button" className="primary" onClick={onUpload}>
                上传专利 PDF
              </button>
            }
          />
        ) : result && result.items.length ? (
          <ResultsTable
            rows={result.items}
            offset={(result.page - 1) * result.page_size}
            metric={metric}
            selected={selected}
            focusedId={focusedId}
            onSelect={onSelect}
            onSelectPage={onSelectPage}
            onJump={onJump}
            onCrop={onCrop}
            onReview={onReview}
          />
        ) : (
          <Empty
            title={result?.total ? '当前页暂无结果' : '暂无匹配的提取结果'}
            description={
              filters.q || filters.target || filters.review || filters.confidence
                ? '调整搜索或筛选条件；筛选不会修改原始提取数据。'
                : '可在上方运行提取，或等待当前任务生成真实结果。历史数据只展示实际已有内容。'
            }
          />
        )}
      </div>
      <Pagination
        page={result?.page ?? filters.page}
        pageSize={result?.page_size ?? filters.page_size}
        total={result?.total ?? 0}
        disabled={!project || resource.loading}
        onChange={(page, page_size) => onFilters({ page, page_size })}
      />
    </div>
  );
}
