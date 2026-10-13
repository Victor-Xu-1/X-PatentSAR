import type { StudyReport } from '../src/api/sarStudyTypes';
import { studyJob, studyReport } from './sar-fixtures';

export function catalogBody(report: StudyReport = studyReport) {
  return {
    detail: 'catalog' as const,
    job: studyJob,
    activity_basis: {
      rule: 'numbered-tenth-decades-v1' as const,
      anchor_rank: 10 as const,
      source_input_sha256: report.input_sha256,
      source_report_sha256: 'a'.repeat(64),
      retained_records: report.molecule_count,
      excluded_records: {},
    },
    report: {
      ...report,
      regions: report.regions.map((region) => ({
        ...region,
        fragments: region.fragments.map((fragment) => ({
          id: fragment.id,
          molecule_ids: [...fragment.molecule_ids],
          molecule_count: fragment.molecule_count,
          is_reference: fragment.is_reference,
          representation: fragment.representation ?? ('port_fragment' as const),
        })),
      })),
    },
  };
}
