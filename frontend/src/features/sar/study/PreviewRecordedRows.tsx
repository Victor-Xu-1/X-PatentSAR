import type { CatalogReport } from '../../../api/sarCatalogTypes';
import type { StudyPreview } from '../../../api/sarStudyTypes';
import { contextLabel } from '../presentation';
import { previewValueText } from './tablePresentation';
import { RecordedDelta } from './RecordedDelta';

/** Raw supporting endpoints/PK, without manufactured statistical conclusions. */
export function PreviewRecordedRows({
  data,
  report,
}: {
  data: StudyPreview;
  report: CatalogReport;
}) {
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
              <RecordedDelta difference={reading.difference} />
            </td>
          </tr>
        );
      })}
    </>
  );
}
