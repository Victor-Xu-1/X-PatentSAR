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
      <p className="sar-hint">{t('候选是研究优先级，不是已验证先导药物；同组不伪造唯一排名。')}</p>
      <details className="sar-compact">
        <summary>{t('候选政策与并列处理')}</summary>
        <p>{report.candidate_policy}</p>
        <p>{t('优先组、Pareto 层与证据覆盖均由报告提供；缺失性质或预测不补值。')}</p>
      </details>
      <div className="sar-card-grid">
        {report.candidates.map((row) => (
          <article className="sar-study-card" key={row.molecule_id}>
            <h3>{row.label}</h3>
            <StudyImage
              jobId={jobId}
              kind="molecule"
              identifier={row.molecule_id}
              label={row.label}
              active={active && row.eligible}
            />
            <RowFacts row={row} contexts={selectedContexts(report)} />
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
