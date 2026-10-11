import { useCallback, useRef, useState } from 'react';
import { ArrowUpRight } from 'lucide-react';
import type { StudyRegionSummary, StudyReport, StudyRow } from '../../../api/sarStudyTypes';
import { sarStudyApi } from '../../../api/sarStudyApi';
import { useTranslation } from '../../../i18n';
import { Loading } from '../../../components/Feedback';
import { SARFailure } from '../SARFailure';
import { useSARResource } from '../useSARResource';
import { GroupPager } from './GroupPager';
import { StudyImage } from './StudyImage';
import { TransformationPreview } from './TransformationPreview';

function Reading({ row, report }: { row: StudyRow; report: StudyReport }) {
  const { t } = useTranslation();
  const context = report.contexts.find((item) => item.id === report.policies[0]?.context_id);
  const values = context ? (row.values[context.id] ?? []) : [];
  return (
    <dl className="sar-branch-readings">
      <div data-activity-strength={context ? row.activity_bands?.[context.id] : undefined}>
        <dt>{context?.name ?? t('活性')}</dt>
        <dd>
          {values.length > 1 ? t('{count} 次测量', { count: values.length }) : (values[0] ?? '—')}
        </dd>
      </div>
      {(['molecular_weight', 'logP', 'tpsa'] as const).map((key, index) => (
        <div key={key}>
          <dt>{['MW', 'LogP', 'TPSA'][index]}</dt>
          <dd>{row.properties[key]?.toFixed(2) ?? '—'}</dd>
        </div>
      ))}
    </dl>
  );
}

export function NetworkBranches({
  report,
  summary,
  jobId,
  active,
  strongest,
  onSource,
}: {
  report: StudyReport;
  summary: StudyRegionSummary;
  jobId: string;
  active: boolean;
  strongest: boolean;
  onSource: (id: string) => void;
}) {
  const { t } = useTranslation();
  const [page, setPage] = useState(1);
  const [preview, setPreview] = useState<{ id: string; request: number } | null>(null);
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
          region_id: summary.region.id,
          scaffold_id: '',
          fragment_id: '',
        },
        signal,
        { column: 'label', direction: 'asc' },
        6,
      ),
    [jobId, report.dataset_id, page, summary.region.id, strongest],
  );
  const rows = useSARResource(
    JSON.stringify(['sar:network-branches', jobId, summary.region.id, page, strongest]),
    active,
    load,
  );
  return (
    <div className="sar-network-branches" aria-label={t('结构分支')}>
      {rows.loading && <Loading />}
      {rows.error && <SARFailure error={rows.error} onRetry={rows.reload} />}
      {rows.validated && rows.data && (
        <>
          <div className="sar-network-branch-grid">
            {rows.data.items.map((row) => (
              <article key={row.molecule_id} className="sar-network-branch">
                <StudyImage
                  jobId={jobId}
                  kind="molecule"
                  identifier={row.molecule_id}
                  atomRegionId={summary.region.id}
                  label={row.label}
                  active={active}
                  inspectable
                />
                <button
                  type="button"
                  className="sar-network-compare"
                  onClick={(event) => {
                    trigger.current = event.currentTarget;
                    setPreview((old) => ({
                      id: row.molecule_id,
                      request: (old?.request ?? 0) + 1,
                    }));
                  }}
                  aria-label={t('比较 {identifier}', { identifier: row.label })}
                >
                  <strong>{row.label}</strong>
                  <ArrowUpRight size={16} />
                </button>
                <Reading row={row} report={report} />
              </article>
            ))}
          </div>
          {!rows.data.items.length && <p>{t('没有符合条件的结构分支')}</p>}
          <GroupPager page={page} size={6} total={rows.data.total} onPage={setPage} />
        </>
      )}
      {preview && (
        <TransformationPreview
          key={preview.id}
          report={report}
          summary={summary}
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
