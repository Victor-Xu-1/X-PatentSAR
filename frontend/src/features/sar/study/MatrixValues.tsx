import type { StudyMatrix, StudyPreview, StudyReport } from '../../../api/sarStudyTypes';
import { useTranslation } from '../../../i18n';
import { contextLabel } from '../presentation';
import { matrixDifference, matrixReadings } from './matrixReadings';
import { propertyComparisonMessage } from './propertyComparisonMessage';
import {
  differenceText,
  previewValueText,
  propertyText,
  studyProperties,
} from './tablePresentation';

const outcomeLabels: Record<string, string> = {
  better: 'SAR 更强',
  worse: 'SAR 更弱',
  equal: '无数值变化',
  indeterminate: '不可判定',
  missing: '未测定',
  context_mismatch: '条件不可比',
};

export function MatrixValues({ data, report }: { data: StudyMatrix; report: StudyReport }) {
  const { t } = useTranslation();
  const rows = matrixReadings(data, report);
  const reference = data.previews[0]!.reference;
  return (
    <>
      <tbody>
        {rows.map(({ context, reference: values, readings, analyzed }) => (
          <tr key={context.id}>
            <th scope="row" title={Object.values(context.context).filter(Boolean).join(' · ')}>
              {contextLabel(context)}
            </th>
            <td
              className="sar-matrix-baseline"
              data-activity-strength={analyzed ? reference.activity_bands?.[context.id] : undefined}
            >
              {previewValueText(values)}
            </td>
            {readings.map((reading, index) => {
              const assessed = analyzed
                ? (reading as StudyPreview['measurements'][number] | undefined)
                : undefined;
              const difference = matrixDifference(assessed);
              return (
                <td
                  key={data.previews[index]!.candidate.molecule_id}
                  data-activity-strength={
                    analyzed
                      ? data.previews[index]!.candidate.activity_bands?.[context.id]
                      : undefined
                  }
                >
                  <span>{previewValueText(reading?.candidate_values ?? [])}</span>
                  {difference != null && (
                    <small className={'sar-matrix-delta is-' + assessed!.comparison}>
                      Δ {difference > 0 ? '+' : ''}
                      {differenceText(difference)}
                    </small>
                  )}
                  {assessed && difference == null && (
                    <small className="sar-matrix-uncertainty">
                      {t(outcomeLabels[assessed.comparison] ?? '不可判定')}
                    </small>
                  )}
                </td>
              );
            })}
          </tr>
        ))}
      </tbody>
      <tbody className="sar-matrix-properties">
        {studyProperties.map((property) => (
          <tr key={property.key}>
            <th scope="row" title={property.unit}>
              {property.label}
            </th>
            <td className="sar-matrix-baseline" title={reference.property_origins[property.key]}>
              {propertyText(reference.properties[property.key], property.key)}
            </td>
            {data.previews.map((preview) => {
              const difference = preview.property_differences[property.key];
              const status = preview.property_statuses?.[property.key];
              const reason = propertyComparisonMessage(status);
              return (
                <td
                  key={preview.candidate.molecule_id}
                  title={preview.candidate.property_origins[property.key]}
                >
                  <span>
                    {propertyText(preview.candidate.properties[property.key], property.key)}
                  </span>
                  {difference != null && (
                    <small className="sar-matrix-delta">
                      Δ {difference > 0 ? '+' : ''}
                      {differenceText(difference, property.key)}
                    </small>
                  )}
                  {difference == null && reason && status !== 'missing' && (
                    <small
                      className="sar-matrix-uncertainty"
                      title={t(reason)}
                      aria-label={t(reason)}
                    >
                      —
                    </small>
                  )}
                </td>
              );
            })}
          </tr>
        ))}
      </tbody>
    </>
  );
}
