import type { StudyReport } from '../../../api/sarStudyTypes';
import { useTranslation } from '../../../i18n';
import { StudyBars } from './StudyBars';
import { contextLabel } from './policyDraft';
import { StudyPolicyNote, hasStrongRule } from './StudyPolicyNote';
import { useState } from 'react';
import type { CountingUnit } from './chartPresentation';
export function StudyOverview({ report }: { report: StudyReport }) {
  const { t } = useTranslation();
  const [unit, setUnit] = useState<CountingUnit>('molecules');
  return (
    <div>
      <dl className="sar-study-stats">
        {[
          ['来源记录', report.molecule_count],
          ['可分析分子', report.eligible_count],
          ['候选数量', report.candidates.length],
        ].map(([label, value]) => (
          <div key={label}>
            <dt>{t(String(label))}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
      <label className="sar-counting-control">
        {t('统计单位')}
        <select
          value={report.counting_contract === 'unique-molecules-v2' ? unit : 'observations'}
          onChange={(e) => setUnit(e.target.value as CountingUnit)}
        >
          <option value="molecules" disabled={report.counting_contract !== 'unique-molecules-v2'}>
            {t('原始编号 / 记录')}
          </option>
          <option value="observations">{t('观察数')}</option>
        </select>
      </label>
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
                controlledUnit={unit}
              />
              <StudyPolicyNote policy={policy} context={context} />
              {hasStrongRule(policy) && (
                <small>
                  {t('强活性')} {distribution.strong_molecules}
                </small>
              )}
            </article>
          );
        })}
      </div>
    </div>
  );
}
