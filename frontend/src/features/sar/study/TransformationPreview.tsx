import { useCallback, useLayoutEffect, useRef, useState } from 'react';
import { X } from 'lucide-react';
import type { StudyRegionSummary, StudyReport } from '../../../api/sarStudyTypes';
import { sarStudyApi } from '../../../api/sarStudyApi';
import { useTranslation } from '../../../i18n';
import { Loading } from '../../../components/Feedback';
import { useSARResource } from '../useSARResource';
import { SARFailure } from '../SARFailure';
import { PageControls } from '../PageControls';
import { StudyImage } from './StudyImage';
import { PreviewMeasurements } from './PreviewMeasurements';
import { preferredScrollBehavior } from '../../../model/motion';
export function TransformationPreview({
  report,
  summary,
  moleculeId,
  jobId,
  active,
  onSource,
  onClose,
  requestId = 0,
}: {
  report: StudyReport;
  summary: StudyRegionSummary;
  moleculeId: string;
  jobId: string;
  active: boolean;
  onSource: (id: string) => void;
  onClose: () => void;
  requestId?: number;
}) {
  const { t } = useTranslation();
  const regionId = summary.region.id;
  const [selected, setSelected] = useState(moleculeId);
  const [page, setPage] = useState(1);
  const fragmentId =
    summary.fragments.find((fragment) => fragment.molecule_ids.includes(moleculeId))?.id ?? '';
  const loadMembers = useCallback(
    (signal: AbortSignal) =>
      sarStudyApi.rows(
        jobId,
        report.dataset_id,
        page,
        { query: '', scope: 'all', scaffold_id: '', region_id: regionId, fragment_id: fragmentId },
        signal,
      ),
    [jobId, report.dataset_id, regionId, fragmentId, page],
  );
  const members = useSARResource(
    JSON.stringify(['sar:preview-members', jobId, regionId, fragmentId, page]),
    active,
    loadMembers,
  );
  const load = useCallback(
    (signal: AbortSignal) =>
      sarStudyApi.preview(jobId, report.dataset_id, regionId, selected, signal),
    [jobId, report.dataset_id, regionId, selected],
  );
  const resource = useSARResource(
    JSON.stringify(['sar:preview', jobId, regionId, selected]),
    active,
    load,
  );
  const data = resource.data;
  const panel = useRef<HTMLElement>(null);
  const revealed = useRef<number | null>(null);
  const settled = useRef<number | null>(null);
  useLayoutEffect(() => {
    const newlyOpened = revealed.current !== requestId;
    if (newlyOpened) {
      revealed.current = requestId;
      if (active && panel.current) {
        panel.current.focus({ preventScroll: true });
        panel.current.scrollIntoView({ block: 'start', behavior: preferredScrollBehavior() });
      }
    }
    if (!active || settled.current === requestId || !(resource.validated || resource.error)) return;
    settled.current = requestId;
    // The loaded content can extend the document beyond its initial scroll limit.
    // Settle only this explicit request, and never pull the user from another control.
    if (!newlyOpened && panel.current === document.activeElement) {
      panel.current?.scrollIntoView({ block: 'start', behavior: preferredScrollBehavior() });
    }
  }, [active, requestId, resource.validated, resource.error]);
  return (
    <section ref={panel} tabIndex={-1} className="sar-transformation" aria-label={t('改造预览')}>
      <header>
        <h3>{t('改造预览')}</h3>
        <button
          type="button"
          className="icon-button"
          aria-label={t('关闭改造预览')}
          onClick={onClose}
        >
          <X size={17} />
        </button>
      </header>
      <label className="sar-preview-member">
        {t('改造化合物')}
        <select
          value={selected}
          onChange={(event) => setSelected(event.target.value)}
          disabled={!members.validated}
        >
          {!members.data?.items.some((row) => row.molecule_id === selected) && (
            <option value={selected}>{data?.candidate.label ?? '…'}</option>
          )}
          {members.data?.items
            .filter((row) => row.molecule_id !== summary.region.molecule_id)
            .map((row) => (
              <option value={row.molecule_id} key={row.molecule_id}>
                {row.label}
              </option>
            ))}
        </select>
      </label>
      {(members.data?.total ?? 0) > 50 && (
        <PageControls
          page={page}
          total={members.data!.total}
          onPage={setPage}
          disabled={!members.validated}
        />
      )}
      {members.error && <SARFailure error={members.error} onRetry={members.reload} />}
      {resource.loading && <Loading label="正在加载改造…" />}
      {resource.error && <SARFailure error={resource.error} onRetry={resource.reload} />}
      {data && resource.validated && (
        <>
          <div className="sar-molecule-comparison">
            {[data.reference, data.candidate].map((row) => (
              <article key={row.molecule_id}>
                <div className="sar-section-heading">
                  <strong>{row.label}</strong>
                  <button
                    type="button"
                    className="link-button"
                    onClick={() => onSource(row.molecule_id)}
                  >
                    {t('查看原文')}
                  </button>
                </div>
                <StudyImage
                  jobId={jobId}
                  kind="molecule"
                  identifier={row.molecule_id}
                  atomRegionId={regionId}
                  label={row.label}
                  active={active}
                  inspectable
                />
              </article>
            ))}
          </div>
          <PreviewMeasurements data={data} report={report} />
        </>
      )}
    </section>
  );
}
