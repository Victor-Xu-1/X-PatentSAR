import { ContractError } from '../../../api/validation';
import type {
  StudyContext,
  StudyMatrix,
  StudyPreview,
  StudyReport,
} from '../../../api/sarStudyTypes';

export function matrixReadings(matrix: StudyMatrix, report: StudyReport) {
  const selected = report.policies.map((item) => item.context_id);
  const contexts = new Map(report.contexts.map((context) => [context.id, context]));
  const records = matrix.previews.map((preview) => {
    if (
      preview.job.input_sha256 !== report.input_sha256 ||
      preview.job.dataset_id !== report.dataset_id ||
      preview.measurements.length !== selected.length ||
      selected.some((id) => !preview.measurements.some((reading) => reading.context_id === id))
    )
      throw new ContractError('$.matrix_report_identity');
    const readings = [...preview.measurements, ...(preview.recorded_measurements ?? [])];
    if (readings.some((reading) => !contexts.has(reading.context_id)))
      throw new ContractError('$.matrix_context');
    return new Map(readings.map((reading) => [reading.context_id, reading]));
  });
  return [
    ...selected.map((id) => contexts.get(id)!),
    ...report.contexts.filter(
      (context) =>
        !selected.includes(context.id) && records.some((readings) => readings.has(context.id)),
    ),
  ].map((context: StudyContext) => {
    const readings = records.map((values) => values.get(context.id));
    const reference = readings.find((reading) => reading !== undefined)?.reference_values ?? [];
    if (
      readings.some(
        (reading) =>
          reading && JSON.stringify(reading.reference_values) !== JSON.stringify(reference),
      )
    )
      throw new ContractError('$.matrix_reference_values');
    return { context, reference, readings, analyzed: selected.includes(context.id) };
  });
}

export function matrixDifference(reading: StudyPreview['measurements'][number] | undefined) {
  return reading && ['better', 'worse', 'equal'].includes(reading.comparison)
    ? reading.raw_difference
    : null;
}
