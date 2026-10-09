import type { StudyReport } from '../../../api/sarStudyTypes';
import { Dialog } from '../../../components/Dialog';
import { useTranslation } from '../../../i18n';
import { SourceAcceptance } from './SourceAcceptance';
import { StudyLimitations } from './StudyLimitations';
import { StudyPolicyNote } from './StudyPolicyNote';

/** One deliberate disclosure; result previews do not repeat operator prose. */
export function StudyReportInfo({
  report,
  historical,
  onClose,
}: {
  report: StudyReport;
  historical: boolean;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  return (
    <Dialog title={t('研究详情')} onClose={onClose}>
      <p>{t('候选是研究优先级，不是已验证先导药物；同组不伪造唯一排名。')}</p>
      {historical && (
        <p className="sar-warning">{t('结果已过期，仅供历史核对；禁止续跑或作为当前结论。')}</p>
      )}
      <SourceAcceptance source={report.source_acceptance} />
      <dl className="sar-facts">
        {[
          ['来源记录', report.molecule_count],
          ['可分析分子', report.eligible_count],
          ['观察数', report.observation_count],
          ['已检查比较', report.strict_pair_count],
          ['已匹配比较', report.matched_pair_count ?? '—'],
          ['可比较证据', report.comparable_pair_count ?? '—'],
        ].map(([label, value]) => (
          <div key={label}>
            <dt>{t(String(label))}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
      <h3>{t('活性规则')}</h3>
      {report.policies.map((policy) => (
        <StudyPolicyNote
          key={policy.context_id}
          policy={policy}
          context={report.contexts.find((c) => c.id === policy.context_id)}
          primary
        />
      ))}
      <details className="sar-compact">
        <summary>{t('候选政策与并列处理')}</summary>
        <p>{report.candidate_policy}</p>
        <p>{t('优先组、Pareto 层与证据覆盖均由报告提供；缺失性质或预测不补值。')}</p>
      </details>
      {report.warnings.length > 0 && <StudyLimitations warnings={report.warnings} />}
    </Dialog>
  );
}
