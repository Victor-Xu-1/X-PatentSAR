import type { StudyReport } from '../src/api/sarStudyTypes';
import { studyFragment, studyJob, studyReport, studyRow } from './sar-fixtures';

export function coherentCatalogReport(): StudyReport {
  const first = studyRow.molecule_id,
    second = 'other-member';
  const bin = { label: 'strong', kind: 'strength', observations: 2, molecules: 2, strong: true };
  return {
    ...studyReport,
    counting_contract: 'unique-molecules-v2',
    molecule_count: 2,
    eligible_count: 2,
    observation_count: 2,
    strict_pair_count: 1,
    contexts: studyReport.contexts.map((context) => ({
      ...context,
      molecule_count: 2,
      observation_count: 2,
    })),
    distributions: studyReport.distributions.map((distribution) => ({
      ...distribution,
      bins: [bin],
      observed_molecules: 2,
      observations: 2,
      missing_molecules: 0,
      unresolved_molecules: 0,
      strong_molecules: 2,
    })),
    scaffolds: [
      {
        ...studyReport.scaffolds[0]!,
        assignment_kind: 'murcko',
        core_region_id: null,
        molecule_count: 2,
        strong_count: 2,
        molecule_ids: [first, second],
        bins: [bin],
      },
    ],
    candidates: [],
    rows: [],
    regions: studyReport.regions.map((summary) => ({
      ...summary,
      matched: 1,
      ambiguous: 0,
      no_variation: false,
      fragments: [
        {
          ...studyFragment,
          molecule_ids: [first],
          bins: [{ ...bin, observations: 1, molecules: 1 }],
        },
        {
          ...studyFragment,
          id: 'changed-fragment',
          molecule_ids: [second],
          is_reference: false,
          bins: [{ ...bin, observations: 1, molecules: 1 }],
        },
      ],
    })),
  };
}

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
