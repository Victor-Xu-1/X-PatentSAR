import type { StudyContext, StudyRow } from '../../../api/sarStudyTypes';
import { useTranslation } from '../../../i18n';
import { contextLabel } from './policyDraft';
import { propertyText, studyProperties } from './tablePresentation';
import { evidenceSummaries, originCopy } from './evidencePresentation';
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
      <p className="sar-candidate-coverage">
        {t(candidateLabels[row.candidate_status])} · {t('证据覆盖')}{' '}
        {Math.round(row.coverage * 100)}%
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
      <dl className="sar-candidate-properties">
        {studyProperties.map((property) => (
          <div key={property.key}>
            <dt>{property.label}</dt>
            <dd>{propertyText(row.properties[property.key])}</dd>
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
                {propertyText(value)}{' '}
                <small>
                  {t(originCopy[row.property_origins[key] ?? 'not_provided'] ?? '来源待确认')}
                </small>
              </dd>
            </div>
          ))}
        </dl>
        <h4>{t('已捕获的预测')}</h4>
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
        <ul>
          {evidenceSummaries(row.reasons).map((reason) => (
            <li key={reason}>{t(reason)}</li>
          ))}
        </ul>
        <details className="sar-technical-evidence">
          <summary>{t('技术证据')}</summary>
          <pre>
            {JSON.stringify(
              {
                activity_status: row.activity_status,
                property_origins: row.property_origins,
                prediction_origin: row.prediction_origin,
                reasons: row.reasons,
              },
              null,
              2,
            )}
          </pre>
        </details>
      </details>
    </div>
  );
}
