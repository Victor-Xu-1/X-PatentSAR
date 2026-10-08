import { useTranslation } from '../../i18n';
import { useState } from 'react';
import type { Compound, Filters, Job, Project, Results } from '../../api/types';
import type { ActivitySourceCallback } from '../../model/activityColumns';
import { availableMetrics } from '../../model/results';
import type { ResultDensity } from '../../model/results';
import type { Resource } from '../../hooks/useResource';
import { Empty, ErrorNotice, Loading } from '../../components/Feedback';
import { ResultsTable } from './ResultsTable';
import { Pagination } from './Pagination';
import { ResultToolbar } from './ResultToolbar';
import { tableActivityColumns } from '../../model/activityColumns';
import { resultColumns } from '../../model/resultColumns';

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
  onPredictionQueued = () => {},
  canPredict = false,
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
  onActivitySource: ActivitySourceCallback;
  onCrop: (row: Compound) => void;
  onReview: (row: Compound) => void;
  onExport: () => void;
  onUpload: () => void;
  onPredictionQueued?: () => void;
  canPredict?: boolean;
}) {
  const { t } = useTranslation();
  const result = resource.data;
  const [density, setDensity] = useState<ResultDensity>('compact');
  const [columnState, setColumnState] = useState<{ project: string | null; hidden: string[] }>({
    project: project?.id ?? null,
    hidden: [],
  });
  if (columnState.project !== (project?.id ?? null))
    setColumnState({ project: project?.id ?? null, hidden: [] });
  const hidden = columnState.project === (project?.id ?? null) ? columnState.hidden : [];
  const setHidden = (next: string[]) =>
    setColumnState({ project: project?.id ?? null, hidden: next });
  const metrics = availableMetrics(
    result?.activity_columns?.map((column) => column.name) ?? result?.metrics ?? [],
    result?.items ?? [],
  );
  const activities = tableActivityColumns(result?.activity_columns, metrics);
  const columns = resultColumns(activities);
  const visibleColumns = columns.filter((column) => !hidden.includes(column.id));
  return (
    <div className="result-data-view">
      <ResultToolbar
        project={project}
        job={job}
        filters={{
          filters,
          targets: result?.targets ?? [],
          onChange: onFilters,
          disabled: !project,
        }}
        display={{
          density,
          onDensity: setDensity,
          disabled: !project,
        }}
        columns={{ columns, hidden, onHidden: setHidden }}
        copy={{
          rows: result?.items ?? [],
          selected,
          columns: visibleColumns,
          activities,
          disabled: !project || resource.loading || Boolean(resource.error),
        }}
        selectedCount={selected.size}
        loading={resource.loading}
        canExport={Boolean(project && result?.total)}
        onReload={resource.reload}
        onExport={onExport}
        canPredict={canPredict}
        onPredictionQueued={onPredictionQueued}
      />
      <div className="results-content" aria-busy={resource.loading}>
        {project && (
          <ResultsTable
            key={project.id}
            projectId={project.id}
            hidden={Boolean(
              resource.error || (resource.loading && !result) || !visibleColumns.length,
            )}
            emptyMessage={result?.total ? t('当前页暂无结果') : t('暂无匹配的提取结果')}
            rows={result?.items ?? []}
            metrics={metrics}
            hiddenColumns={hidden}
            filters={filters}
            queryLoading={resource.loading}
            onFilters={onFilters}
            onHideColumn={(id) => setHidden([...hidden, id])}
            {...(result?.activity_columns === undefined
              ? {}
              : { activityColumns: result.activity_columns })}
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
        )}
        {resource.error ? (
          <ErrorNotice error={resource.error} onRetry={resource.reload} />
        ) : resource.loading && !result ? (
          <Loading label={t('正在查询真实结构与活性结果…')} />
        ) : !project ? (
          <Empty
            title={t('开始探索专利中的结构与活性')}
            description={t(
              '上传一份原始专利 PDF，或从项目列表打开已有结果。所有结构、指标和来源均来自真实提取，不生成演示数据。',
            )}
            action={
              <button type="button" className="primary" onClick={onUpload}>
                {t('上传专利 PDF')}
              </button>
            }
          />
        ) : !visibleColumns.length ? (
          <Empty
            title={t('所有列已隐藏')}
            description={t('数据仍然保留，可恢复全部列或在“显示列”中选择。')}
            action={
              <button type="button" onClick={() => setHidden([])}>
                {t('显示全部列')}
              </button>
            }
          />
        ) : null}
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
