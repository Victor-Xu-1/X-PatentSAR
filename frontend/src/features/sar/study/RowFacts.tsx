import type { StudyContext, StudyRow } from '../../../api/sarStudyTypes';
import { useTranslation } from '../../../i18n';
import { contextLabel } from './policyDraft';
import { propertyText, studyProperties } from './tablePresentation';
export const candidateLabels = {
  selected: '研究已选候选',
  not_selected: '研究未选候选',
  unranked: '研究未排序',
  ineligible: 'SAR 不合格',
  partial: '研究部分证据',
} as const;
export function RowFacts({ row, contexts }: { row: StudyRow; contexts: StudyContext[] }) {
  const { t } = useTranslation();
  return (
    <div>
      <p>
        {t(candidateLabels[row.candidate_status])} · {t('证据覆盖')} {row.coverage}
      </p>
      <dl className="sar-facts">
        {contexts.map((context) => (
          <div key={context.id}>
            <dt>{contextLabel(context)}</dt>
            <dd title={row.activity_status[context.id]}>
              {(row.values[context.id] ?? []).map((value, index) => (
                <span key={index}>{value}</span>
              ))}
            </dd>
          </div>
        ))}
      </dl>
      <details className="sar-compact">
        <summary>{t('研究性质与已有预测')}</summary>
        <dl className="sar-facts">
          {Object.entries(row.properties).map(([key, value]) => (
            <div key={key}>
              <dt>{studyProperties.find((p) => p.key === key)?.label ?? key}</dt>
              <dd title={value == null ? undefined : String(value)}>
                {propertyText(value)} · {row.property_origins[key] ?? 'not_provided'}
              </dd>
            </div>
          ))}
        </dl>
        <h4>
          {t('已捕获的预测')} · {row.prediction_origin}
        </h4>
        <dl className="sar-facts">
          {Object.entries(row.predictions).map(([key, value]) => (
            <div key={key}>
              <dt>{key}</dt>
              <dd>{value ?? '—'}</dd>
            </div>
          ))}
        </dl>
        {!Object.keys(row.predictions).length && <p>{t('未提供预测')}</p>}
      </details>
      <p>
        {t('Pareto 层')} {row.pareto_front ?? '—'} · {t('优先组')} {row.priority_group ?? '—'}
      </p>
      <details className="sar-compact">
        <summary>{t('证据依据')}</summary>
        <ul className="sar-raw-reasons">
          {Object.entries(row.activity_status).map(([id, value]) => (
            <li key={id}>
              {contexts.find((c) => c.id === id)?.name ?? t('活性指标')}: {value}
            </li>
          ))}
          {row.reasons.map((reason, i) => (
            <li key={i}>{reason}</li>
          ))}
        </ul>
      </details>
    </div>
  );
}
