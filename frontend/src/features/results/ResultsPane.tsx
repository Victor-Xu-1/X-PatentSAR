import { Download } from 'lucide-react';
import { useState } from 'react';
import type { Activity, Compound, Filters, Job, Project, Results } from '../../api/types';
import { availableMetrics } from '../../model/results';
import type { ResultDensity } from '../../model/results';
import type { Resource } from '../../hooks/useResource';
import { Empty, ErrorNotice, Loading } from '../../components/Feedback';
import { Metrics } from './Metrics';
import { ResultFilters } from './ResultFilters';
import { ResultsTable } from './ResultsTable';
import { Pagination } from './Pagination';
import { ExtractionNotice } from './ExtractionNotice';
import { ResultDisplayControls } from './ResultDisplayControls';

export function ResultsPane({
  project,
  job = null,
  resource,
  filters,
  selected,
  focusedId,
  onFilters,
  onSelect,
  onSelectPage,
  onJump,
  onActivitySource,
  onCrop,
  onReview,
  onExport,
  onUpload,
}: {
  project: Project | null;
  job?: Job | null;
  resource: Resource<Results>;
  filters: Filters;
  selected: Set<string>;
  focusedId: string | null;
  onFilters: (patch: Partial<Filters>) => void;
  onSelect: (id: string) => void;
  onSelectPage: (checked: boolean) => void;
  onJump: (row: Compound) => void;
  onActivitySource: (activity: Activity) => void;
  onCrop: (row: Compound) => void;
  onReview: (row: Compound) => void;
  onExport: () => void;
  onUpload: () => void;
}) {
  const result = resource.data;
  const [density, setDensity] = useState<ResultDensity>('compact');
  const [selection, setSelection] = useState<string[] | null>(null);
  const metrics = availableMetrics(result?.metrics ?? [], result?.items ?? []);
  const visibleMetrics =
    selection === null ? metrics : metrics.filter((name) => selection.includes(name));
  return (
    <div className="result-data-view">
      <Metrics project={project} />
      {project && <ExtractionNotice project={project} job={job} />}
      <ResultFilters
        filters={filters}
        targets={result?.targets ?? []}
        onChange={onFilters}
        total={result?.total ?? null}
        disabled={!project}
      />
      <ResultDisplayControls
        metrics={metrics}
        visibleMetrics={visibleMetrics}
        density={density}
        onDensity={setDensity}
        onMetrics={setSelection}
        disabled={!project}
      />
      <div className="selection-bar">
        <span>
          {selected.size
            ? `已选择 ${selected.size} 个化合物（跨页保留）`
            : '点击编号对照原图与重绘 · 活性页码返回独立来源'}
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
            metrics={visibleMetrics}
            density={density}
            selected={selected}
            focusedId={focusedId}
            onSelect={onSelect}
            onSelectPage={onSelectPage}
            onJump={onJump}
            onActivitySource={onActivitySource}
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
