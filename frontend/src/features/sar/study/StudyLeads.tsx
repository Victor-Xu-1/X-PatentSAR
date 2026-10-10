import type { StudyReport } from '../../../api/sarStudyTypes';
import { useTranslation } from '../../../i18n';
import { StudyImage } from './StudyImage';
import { RowFacts } from './RowFacts';
import { selectedContexts } from './tablePresentation';
export function StudyLeads({
  report,
  jobId,
  active,
  onSource,
}: {
  report: StudyReport;
  jobId: string;
  active: boolean;
  onSource: (id: string) => void;
}) {
  const { t } = useTranslation();
  return (
    <div>
      <div className="sar-card-grid sar-lead-grid">
        {report.candidates.map((row) => (
          <article className="sar-study-card sar-lead-card" key={row.molecule_id}>
            <div className="sar-lead-heading">
              <h3>{row.label}</h3>
              <span>
                {t('优先组')} {row.priority_group ?? '—'}
              </span>
            </div>
            <StudyImage
              jobId={jobId}
              kind="molecule"
              identifier={row.molecule_id}
              label={row.label}
              active={active && row.eligible}
              inspectable
              inspectionTrigger="image"
            />
            <RowFacts row={row} contexts={selectedContexts(report)} compact />
            <button type="button" onClick={() => onSource(row.molecule_id)}>
              {t('来源详情')}
            </button>
          </article>
        ))}
      </div>
      {!report.candidates.length && <p>{t('暂无有支持证据的候选')}</p>}
    </div>
  );
}
