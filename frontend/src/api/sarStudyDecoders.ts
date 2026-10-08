import {
  array,
  boolean,
  count,
  defaulted,
  object,
  oneOf,
  positive,
  string,
  ContractError,
} from './validation';
import { additions, checkPage, decodeRegion, hex, nullOr, unique } from './sarDecoders';
import { decodeSARJob } from './sarJobDecoders';
import { studyBin, studyContext, studyPolicy, studyRow } from './sarStudyRowDecoders';
import type { Decoder } from './validation';
import type { StudyOverview, StudyProfile, StudyReport, StudyRows } from './sarStudyTypes';
const truth: Decoder<true> = (v, p = '$') => {
  if (v !== true) throw new ContractError(p);
  return true;
};
const falsehood: Decoder<false> = (v, p = '$') => {
  if (v !== false) throw new ContractError(p);
  return false;
};
const one: Decoder<1> = (v, p = '$') => {
  if (v !== 1) throw new ContractError(p);
  return 1;
};
export const decodeStudyProfile: Decoder<StudyProfile> = (v, p = '$') => {
  const result = object({
    dataset_id: string,
    dataset_revision: positive,
    contexts: array(studyContext),
    regions: array(decodeRegion),
  })(v, p);
  unique(
    result.contexts.map((c) => c.id),
    p + '.contexts',
  );
  unique(
    result.regions.map((r) => r.id),
    p + '.regions',
  );
  if (
    result.contexts.length > 1000 ||
    result.regions.some((r) => r.dataset_id !== result.dataset_id)
  )
    throw new ContractError(p);
  return result;
};
const scaffold = object({
  id: string,
  smiles: nullOr(string),
  molecule_count: count,
  strong_count: count,
  bins: array(studyBin),
  molecule_ids: array(string),
  descriptive_only: defaulted(truth, true),
  assignment_kind: defaulted(oneOf(['murcko', 'confirmed_core']), 'murcko'),
  core_region_id: defaulted(nullOr(string), null),
});
const fragment = object({
  id: string,
  smiles: string,
  molecule_ids: array(string),
  molecule_count: count,
  strong_count: count,
  bins: array(studyBin),
  better: count,
  worse: count,
  indeterminate: count,
  missing: count,
  is_reference: boolean,
});
const regionSummary = object({
  region: decodeRegion,
  reference_label: string,
  reference_fragment_id: nullOr(string),
  fixed_background_sha256: hex(64),
  matched: count,
  not_matched: count,
  ambiguous: count,
  ineligible: count,
  comparable: count,
  no_variation: boolean,
  fragments: array(fragment),
  independent_backgrounds: defaulted(one, 1),
});
export const decodeStudyReport: Decoder<StudyReport> = (v, p = '$') => {
  const result = object({
    schema_version: defaulted(one, 1),
    dataset_id: string,
    dataset_revision: positive,
    title: string,
    input_sha256: hex(64),
    engine_sha256: hex(64),
    research_only: defaulted(truth, true),
    article_algorithm_reproduced: defaulted(falsehood, false),
    molecule_count: count,
    eligible_count: count,
    observation_count: count,
    strict_pair_count: count,
    contexts: array(studyContext),
    policies: array(studyPolicy),
    distributions: array(
      object({
        context_id: hex(64),
        bins: array(studyBin),
        observed_molecules: count,
        observations: count,
        missing_molecules: count,
        unresolved_molecules: count,
        strong_molecules: count,
      }),
    ),
    scaffolds: array(scaffold),
    regions: array(regionSummary),
    candidates: array(studyRow),
    rows: array(studyRow),
    warnings: array(string),
    candidate_policy: defaulted(string, 'strict-context-pareto-v1'),
  })(v, p);
  const contextIds = result.contexts.map((c) => c.id);
  unique(contextIds, p + '.contexts');
  unique(
    result.policies.map((c) => c.context_id),
    p + '.policies',
  );
  unique(
    result.regions.map((r) => r.region.id),
    p + '.regions',
  );
  unique(
    result.scaffolds.map((s) => s.id),
    p + '.scaffolds',
  );
  if (
    result.eligible_count > result.molecule_count ||
    result.policies.length < 1 ||
    result.policies.length > 8 ||
    result.policies.some((c) => !contextIds.includes(c.context_id)) ||
    result.distributions.some(
      (d) => !contextIds.includes(d.context_id) || d.strong_molecules > d.observed_molecules,
    ) ||
    result.scaffolds.some((s) => s.strong_count > s.molecule_count) ||
    result.regions.some(
      (r) =>
        r.region.dataset_id !== result.dataset_id ||
        r.region.dataset_revision !== result.dataset_revision ||
        r.fragments.some((f) => f.strong_count > f.molecule_count),
    )
  )
    throw new ContractError(p);
  return {
    ...result,
    ...additions(v, { matched_pair_count: count, comparable_pair_count: count }, p),
  };
};
export const decodeStudyOverview: Decoder<StudyOverview> = object({
  job: decodeSARJob,
  report: decodeStudyReport,
});
export const decodeStudyRows: Decoder<StudyRows> = (v, p = '$') => {
  const result = object({
    items: array(studyRow),
    total: count,
    page: positive,
    page_size: positive,
    job: decodeSARJob,
  })(v, p);
  checkPage(result, p);
  return result;
};
export const decodeStudyDrawing = (v: unknown, p = '$') => {
  const result = object({ id: string, svg: string })(v, p);
  if (result.svg.length > 1024 * 1024) throw new ContractError(p);
  return result;
};
