import type { StudyPreview, StudyReport } from '../../../api/sarStudyTypes';
import { useTranslation } from '../../../i18n';
import { contextLabel } from '../presentation';
import { previewValueText } from './tablePresentation';

/** Raw supporting endpoints/PK, without manufactured statistical conclusions. */
export function PreviewRecordedRows({ data, report }: { data: StudyPreview; report: StudyReport }) {
  const { t } = useTranslation();
  return (
    <>
      {(data.recorded_measurements ?? []).map((reading) => {
        const context = report.contexts.find((item) => item.id === reading.context_id)!;
        return (
          <tr key={reading.context_id} className="sar-preview-recorded">
            <th scope="row" title={Object.values(context.context).filter(Boolean).join(' · ')}>
              {contextLabel(context)}
            </th>
            {[reading.reference_values, reading.candidate_values].map((values, index) => (
              <td key={index}>
                <span className="sar-preview-compound-label" aria-hidden="true">
                  {index === 0 ? data.reference.label : data.candidate.label}
                </span>
                {previewValueText(values)}
              </td>
            ))}
            <td className="sar-preview-change">
              <span title={t('未纳入本次统计')} aria-label={t('未纳入本次统计')}>
                —
              </span>
            </td>
          </tr>
        );
      })}
    </>
  );
}
