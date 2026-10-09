import { useCallback, useState } from 'react';
import { sarApi } from '../../api/sarApi';
import type { JobList, Molecule, Region, SARJob } from '../../api/sarTypes';
import { useSARResource } from './useSARResource';
import { Loading } from '../../components/Feedback';
import { SARFailure } from './SARFailure';
import { useTranslation } from '../../i18n';
import { isActiveJob } from './presentation';
import { SourceLinks } from './SourceLinks';
import { AnalysisForm } from './AnalysisForm';
import { MoleculeBrowser } from './MoleculeBrowser';
import { RegionSelector } from './RegionSelector';
import { SARJobs } from './SARJobs';
import { SARJobResults } from './SARJobResults';
import { StudySetup } from './study/StudySetup';
import { SourceAcceptance } from './study/SourceAcceptance';
import { DeleteDataset } from './DeleteDataset';

const activeList = (list: JobList) => list.items.some(isActiveJob);
export function DatasetWorkbench({
  datasetId,
  active,
  jobId,
  onJob,
  onRemoved,
  scope = '',
}: {
  datasetId: string;
  active: boolean;
  jobId: string | null;
  onJob: (id: string | null) => void;
  onRemoved: () => void;
  scope?: string;
}) {
  const { t } = useTranslation();
  const [reference, setReference] = useState<Molecule | null>(null);
  const [region, setRegion] = useState<Region | null>(null);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [setupOpen, setSetupOpen] = useState(!jobId);
  const load = useCallback((signal: AbortSignal) => sarApi.dataset(datasetId, signal), [datasetId]);
  const dataset = useSARResource(`sar:dataset:${datasetId}`, active, load);
  const loadJobs = useCallback(
    (signal: AbortSignal) => sarApi.jobs(datasetId, signal),
    [datasetId],
  );
  const jobs = useSARResource(`sar:jobs:${datasetId}`, active, loadJobs, {
    milliseconds: 3000,
    while: activeList,
  });
  const ready = dataset.validated && jobs.validated;
  function createdJob(job: SARJob) {
    setSetupOpen(false);
    jobs.reload();
    dataset.reload();
    onJob(job.id);
  }
  return (
    <div className="sar-workbench">
      {dataset.loading && <Loading />}
      {dataset.error && <SARFailure error={dataset.error} onRetry={dataset.reload} />}
      {dataset.data && (
        <>
          <section
            className={
              'sar-panel sar-dataset-summary' + (jobId ? ' sar-dataset-summary-collapsed' : '')
            }
          >
            <details open={jobId ? undefined : true}>
              <summary>
                {t('数据集详情')} · {dataset.data.row_count} {t('来源记录')}
              </summary>
              <div className="sar-section-heading">
                <h2>{dataset.data.title}</h2>
                <button
                  type="button"
                  onClick={() => {
                    dataset.reload();
                    jobs.reload();
                  }}
                >
                  {t('刷新')}
                </button>
              </div>
              <p>
                {t('{rows} 行 · {eligible} 行可分析 · {issues} 项问题', {
                  rows: dataset.data.row_count,
                  eligible: dataset.data.eligible_count,
                  issues: dataset.data.issue_count,
                })}
              </p>
              {dataset.data.stale && (
                <output className="sar-warning">
                  {t('数据集已过期：保留旧结果供核对，请显式创建新快照。')}
                </output>
              )}
              <SourceLinks dataset={dataset.data} />
              {dataset.data.source_kind === 'project' && !jobId && (
                <SourceAcceptance source={dataset.data.source_acceptance} />
              )}
              <details className="sar-compact">
                <summary>{t('数据集管理')}</summary>
                {dataset.data.input_row_count !== undefined && (
                  <p>
                    {t('{records} 条原始记录 · {rows} 个合并分子行', {
                      records: dataset.data.input_row_count,
                      rows: dataset.data.row_count,
                    })}
                  </p>
                )}
                <DeleteDataset
                  dataset={dataset.data}
                  active={active}
                  disabled={!ready}
                  scope={scope}
                  onRemoved={onRemoved}
                />
              </details>
            </details>
          </section>
          {jobs.error && <SARFailure error={jobs.error} onRetry={jobs.reload} />}
          {jobId && (
            <SARJobResults
              key={jobId}
              known={jobs.data?.items.find((job) => job.id === jobId) ?? null}
              dataset={dataset.data}
              jobId={jobId}
              active={active}
              disabled={!dataset.validated}
              scope={scope}
              reference={reference}
              onJob={(id) => {
                jobs.reload();
                dataset.reload();
                onJob(id);
              }}
            />
          )}
          <details
            className="sar-compact"
            open={setupOpen}
            onToggle={(event) => setSetupOpen(event.currentTarget.open)}
          >
            <summary>{t('研究设置')}</summary>
            <div hidden={!setupOpen}>
              <StudySetup
                dataset={dataset.data}
                active={active && setupOpen}
                disabled={!ready || Boolean(jobs.data?.items.some(isActiveJob))}
                scope={scope}
                onJob={createdJob}
              />
            </div>
          </details>
          <details
            className="sar-compact sar-reference-mode"
            open={advancedOpen}
            onToggle={(event) => setAdvancedOpen(event.currentTarget.open)}
          >
            <summary>{t('单参考比较（高级）')}</summary>
            <div hidden={!advancedOpen}>
              <MoleculeBrowser
                dataset={dataset.data}
                active={active && advancedOpen && dataset.validated}
                referenceId={reference?.id ?? null}
                onReference={(molecule) => {
                  if (
                    reference?.id !== molecule.id ||
                    reference.graph_sha256 !== molecule.graph_sha256
                  ) {
                    setReference(molecule);
                    setRegion(null);
                  }
                }}
              />
              <div className="sar-analysis-grid">
                {reference && (
                  <RegionSelector
                    key={`${dataset.data.revision}:${reference.id}:${reference.graph_sha256}`}
                    dataset={dataset.data}
                    reference={reference}
                    active={active && advancedOpen}
                    disabled={!dataset.validated}
                    scope={scope}
                    onRegion={setRegion}
                  />
                )}
                <AnalysisForm
                  dataset={dataset.data}
                  region={region}
                  busy={!ready || Boolean(jobs.data?.items.some(isActiveJob))}
                  active={active && advancedOpen}
                  scope={scope}
                  onJob={createdJob}
                />
              </div>
            </div>
          </details>
          <details className="sar-compact">
            <summary>{t('研究任务历史')}</summary>
            <SARJobs
              dataset={dataset.data}
              resource={{ ...jobs, error: null }}
              selectedId={jobId}
              disabled={!ready}
              active={active}
              scope={scope}
              onSelect={onJob}
              onRemoved={(id) => {
                jobs.reload();
                if (jobId === id) onJob(null);
              }}
            />
          </details>
        </>
      )}
    </div>
  );
}
