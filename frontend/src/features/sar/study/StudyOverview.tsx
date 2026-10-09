import type { StudyReport } from '../../../api/sarStudyTypes';
import { useTranslation } from '../../../i18n';
import { StudyBars } from './StudyBars';
import { contextLabel } from './policyDraft';
export function StudyOverview({ report }: { report: StudyReport }) {
  const { t } = useTranslation();
  return (
    <div>
      <dl className="sar-study-stats">
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
      <div className="sar-card-grid sar-overview-charts">
        {report.distributions.map((distribution) => {
          const context = report.contexts.find((c) => c.id === distribution.context_id);
          const declaration = report.context_declarations?.find(
            (item) => item.context_id === distribution.context_id,
          );
          const policy = report.policies.find(
            (item) => item.context_id === distribution.context_id,
          );
          return (
            <article className="sar-study-card" key={distribution.context_id}>
              <h3>{context ? contextLabel(context) : distribution.context_id}</h3>
              {context && (
                <details className="sar-context-detail">
                  <summary>{t(declaration ? '原文条件人工记录' : '记录条件')}</summary>
                  <p className="sar-hint">
                    {Object.entries({ ...context.context, ...declaration?.fields })
                      .map(([key, value]) => key + ': ' + (value ?? '—'))
                      .join(' · ')}
                  </p>
                  {declaration && <p>{declaration.note}</p>}
                </details>
              )}
              <StudyBars
                bins={distribution.bins}
                layout="donut"
                countingContract={report.counting_contract}
                direction={policy?.direction}
              />
              <p>
                {t('已观察 {observed} · 缺失 {missing} · 未确定 {unresolved} · 强活性 {strong}', {
                  observed: distribution.observed_molecules,
                  missing: distribution.missing_molecules,
                  unresolved: distribution.unresolved_molecules,
                  strong: distribution.strong_molecules,
                })}
              </p>
              <small>
                {t('{molecules} 个分子 · {observations} 条观察', {
                  molecules: distribution.observed_molecules,
                  observations: distribution.observations,
                })}
              </small>
            </article>
          );
        })}
      </div>
    </div>
  );
}
