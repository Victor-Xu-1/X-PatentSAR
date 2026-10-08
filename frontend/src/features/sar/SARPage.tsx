import { useCallback, useEffect, useRef, useState } from 'react';
import { sarApi } from '../../api/sarApi';
import type { Dataset } from '../../api/sarTypes';
import type { Route } from '../../model/route';
import { emptyRoute } from '../../model/route';
import { useResource } from '../../hooks/useResource';
import { Empty, Loading } from '../../components/Feedback';
import { SARFailure } from './SARFailure';
import { useTranslation } from '../../i18n';
import { SARImport } from './SARImport';
import { DatasetWorkbench } from './DatasetWorkbench';

export function SARPage({
  active,
  route,
  navigate,
}: {
  active: boolean;
  route: Route;
  navigate: (route: Route) => void;
}) {
  const { t } = useTranslation();
  const activeView = useRef(active);
  useEffect(() => {
    activeView.current = active;
  }, [active]);
  const [selection, setSelection] = useState({
    datasetId: route.sarDatasetId ?? null,
    jobId: route.sarJobId ?? null,
  });
  const datasetId = route.view === 'sar' ? (route.sarDatasetId ?? null) : selection.datasetId;
  const jobId = route.view === 'sar' ? (route.sarJobId ?? null) : selection.jobId;
  const [importOpen, setImportOpen] = useState(!route.sarDatasetId);
  const load = useCallback((signal: AbortSignal) => sarApi.datasets(signal), []);
  const datasets = useResource(active ? 'sar:datasets' : null, load);
  function select(id: string | null, nextJob: string | null = null) {
    setSelection({ datasetId: id, jobId: nextJob });
    if (activeView.current)
      navigate({
        ...emptyRoute,
        view: 'sar',
        projectId: route.view === 'sar' ? route.projectId : null,
        ...(id ? { sarDatasetId: id } : {}),
        ...(nextJob ? { sarJobId: nextJob } : {}),
      });
  }
  function created(dataset: Dataset) {
    datasets.reload();
    setImportOpen(false);
    select(dataset.id);
  }
  return (
    <div className="sar-page" hidden={!active}>
      <header className="sar-page-heading">
        <div>
          <h1>{t('SAR 分析')}</h1>
          <p>{t('严格参考比较')}</p>
        </div>
        <div className="sar-actions">
          <button type="button" onClick={datasets.reload}>
            {t('刷新')}
          </button>
          <button
            type="button"
            aria-expanded={importOpen}
            onClick={() => setImportOpen((old) => !old)}
          >
            {t('导入数据')}
          </button>
        </div>
      </header>
      <p className="sar-intro">
        {t('选择参考分子和变化区域，比较同一实验指标；不生成全系列评分，也不复现文章结论。')}
      </p>
      {datasets.loading && <Loading />}
      {datasets.error && <SARFailure error={datasets.error} onRetry={datasets.reload} />}
      {datasets.data?.items.length === 0 && (
        <Empty
          title="尚无 SAR 数据集"
          description="选择已提取项目快照或导入 CSV。打开页面不会创建数据集或启动分析。"
        />
      )}
      <label className="sar-dataset-picker">
        {t('SAR 数据集')}
        <select value={datasetId ?? ''} onChange={(e) => select(e.target.value || null)}>
          <option value="">{t('SAR 数据集')}</option>
          {datasetId && !datasets.data?.items.some((dataset) => dataset.id === datasetId) && (
            <option value={datasetId}>{datasetId}</option>
          )}
          {datasets.data?.items.map((dataset) => (
            <option value={dataset.id} key={dataset.id}>
              {dataset.title}
            </option>
          ))}
        </select>
      </label>
      <div hidden={!importOpen}>
        <SARImport
          active={active && importOpen}
          sourceProjectId={route.view === 'sar' ? route.projectId : null}
          onCreated={created}
        />
      </div>
      {datasetId && (
        <DatasetWorkbench
          key={datasetId}
          datasetId={datasetId}
          active={active}
          jobId={jobId}
          onJob={(id) => select(datasetId, id)}
          onRemoved={() => {
            datasets.reload();
            setImportOpen(true);
            select(null);
          }}
        />
      )}
    </div>
  );
}
