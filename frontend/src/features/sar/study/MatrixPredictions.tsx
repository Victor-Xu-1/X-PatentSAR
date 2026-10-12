import type { StudyMatrix } from '../../../api/sarStudyTypes';
import { useTranslation } from '../../../i18n';
import { propertyText } from './tablePresentation';

/** Existing predictions stay separate; opening this never runs a model. */
export function MatrixPredictions({ data }: { data: StudyMatrix }) {
  const { t } = useTranslation();
  const rows = [data.previews[0]!.reference, ...data.previews.map((item) => item.candidate)];
  const keys = [...new Set(rows.flatMap((row) => Object.keys(row.predictions)))];
  if (!keys.length) return null;
  return (
    <details className="sar-compact sar-matrix-predictions">
      <summary>{t('已有 ADMET 预测')}</summary>
      <div className="sar-table-scroll">
        <table aria-label={t('已有 ADMET 预测')}>
          <thead>
            <tr>
              <th scope="col">{t('预测指标')}</th>
              {rows.map((row) => (
                <th key={row.molecule_id} scope="col">
                  {row.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {keys.map((key) => (
              <tr key={key}>
                <th scope="row">{key}</th>
                {rows.map((row) => (
                  <td key={row.molecule_id} title={row.prediction_origin}>
                    {propertyText(row.predictions[key])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}
