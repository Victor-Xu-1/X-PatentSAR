import { useCallback, useMemo, useRef, useState } from 'react';
import type { StudyRegionSummary, StudyReport } from '../../../api/sarStudyTypes';
import { sarStudyApi } from '../../../api/sarStudyApi';
import { useTranslation } from '../../../i18n';
import { Loading } from '../../../components/Feedback';
import { SARFailure } from '../SARFailure';
import { useSARResource } from '../useSARResource';
import { GroupPager } from './GroupPager';
import { TransformationPreview } from './TransformationPreview';
import { NetworkBranchCard } from './NetworkBranchCard';
import { networkRowSites } from './networkSites';

export function NetworkBranches({
  report,
  summary,
  summaries = [],
  referenceId = summary?.region.molecule_id ?? '',
  jobId,
  active,
  strongest,
  fragments = false,
  onSource,
}: {
  report: StudyReport;
  summary?: StudyRegionSummary | undefined;
  summaries?: StudyRegionSummary[];
  referenceId?: string;
  jobId: string;
  active: boolean;
  strongest: boolean;
  fragments?: boolean;
  onSource: (id: string) => void;
}) {
  const { t } = useTranslation();
  const [page, setPage] = useState(1);
  const [preview, setPreview] = useState<{
    id: string;
    request: number;
    summary: StudyRegionSummary;
  } | null>(null);
  const sites = summary ? [summary] : summaries;
  const siteOrder = useMemo(
    () =>
      new Map(
        (summaries.length ? summaries : summary ? [summary] : []).map((item, index) => [
          item.region.id,
          index,
        ]),
      ),
    [summaries, summary],
  );
  const trigger = useRef<HTMLButtonElement | null>(null);
  const load = useCallback(
    (signal: AbortSignal) =>
      sarStudyApi.rows(
        jobId,
        report.dataset_id,
        page,
        {
          query: '',
          scope: strongest ? 'strong_changes' : 'changes',
          region_id: summary?.region.id ?? '',
          reference_id: referenceId,
          scaffold_id: '',
          fragment_id: '',
        },
        signal,
        { column: 'label', direction: 'asc' },
        6,
      ),
    [jobId, report.dataset_id, page, summary?.region.id, referenceId, strongest],
  );
  const rows = useSARResource(
    JSON.stringify([
      'sar:network-branches',
      jobId,
      referenceId,
      summary?.region.id ?? '',
      page,
      strongest,
    ]),
    active,
    load,
  );
  return (
    <div className="sar-network-branches" aria-label={t('结构分支')}>
      {rows.loading && <Loading />}
      {rows.error && <SARFailure error={rows.error} onRetry={rows.reload} />}
      {rows.validated && rows.data && (
        <>
          {summary?.no_variation && <output>{t('该区域没有观察到结构变化。')}</output>}
          <div className="sar-network-branch-grid">
            {rows.data.items.map((row) => (
              <NetworkBranchCard
                key={row.molecule_id}
                row={row}
                report={report}
                sites={networkRowSites(sites, row.molecule_id)}
                siteOrder={siteOrder}
                jobId={jobId}
                active={active}
                fragments={fragments}
                onCompare={(chosen, id, button) => {
                  trigger.current = button;
                  setPreview((old) => ({ id, summary: chosen, request: (old?.request ?? 0) + 1 }));
                }}
              />
            ))}
          </div>
          {!rows.data.items.length && <p>{t('没有符合条件的结构分支')}</p>}
          <GroupPager page={page} size={6} total={rows.data.total} onPage={setPage} />
        </>
      )}
      {preview && (
        <TransformationPreview
          key={preview.id + ':' + preview.summary.region.id}
          report={report}
          summary={preview.summary}
          moleculeId={preview.id}
          requestId={preview.request}
          jobId={jobId}
          active={active}
          onSource={onSource}
          onClose={() => {
            setPreview(null);
            if (trigger.current?.isConnected) trigger.current.focus();
          }}
        />
      )}
    </div>
  );
}
