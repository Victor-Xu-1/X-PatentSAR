import type { CatalogReport } from '../../../api/sarCatalogTypes';
import type { StudyRow } from '../../../api/sarStudyTypes';
import { useTranslation } from '../../../i18n';
import { selectedContexts } from './tablePresentation';

export function NetworkBranchReadings({ row, report }: { row: StudyRow; report: CatalogReport }) {
  const { t } = useTranslation();
  return (
    <dl className="sar-branch-readings" title={t('活性与理化值对应完整分子')}>
      {selectedContexts(report).map((context) => {
        const values = row.values[context.id] ?? [];
        return (
          <div
            key={context.id}
            className="sar-branch-measurement"
            data-activity-strength={row.activity_bands?.[context.id]}
          >
            <dt>{context.name}</dt>
            <dd>
              {values.length > 1 ? t('{count} 次测量', { count: values.length }) : values[0] || '—'}
            </dd>
          </div>
        );
      })}
      {(['molecular_weight', 'logP', 'tpsa'] as const).map((key, index) => (
        <div key={key}>
          <dt>{['MW', 'LogP', 'TPSA'][index]}</dt>
          <dd>{row.properties[key]?.toFixed(2) ?? '—'}</dd>
        </div>
      ))}
    </dl>
  );
}
