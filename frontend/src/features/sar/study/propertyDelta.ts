import type { PropertyComparisonStatus, StudyRow } from '../../../api/sarStudyTypes';
import { differenceText, studyProperties } from './tablePresentation';

type PropertySource = Pick<StudyRow, 'properties' | 'property_origins'>;
interface DifferenceView {
  reference: PropertySource;
  candidate: PropertySource;
  property_differences: Readonly<Record<string, number | null | undefined>>;
  property_statuses?: Readonly<Record<string, PropertyComparisonStatus>>;
}
const continuous: ReadonlySet<string> = new Set(
  studyProperties
    .filter((property) => property.unit !== '#' && property.key !== 'Solubility_AqSolDB')
    .map((property) => property.key),
);
const nativeOrigins: ReadonlySet<string> = new Set([
  'computed_rdkit',
  'verified_project_descriptor',
]);

/** Display only: never changes a stored number, ranking, comparison or outcome. */
export function propertyDelta(data: DifferenceView, key: string) {
  const difference = data.property_differences[key];
  if (difference == null || !Number.isFinite(difference))
    return { text: '—', raw: null, approximate: false };
  const first = data.reference.properties[key];
  const second = data.candidate.properties[key];
  // A four-epsilon guard applies only to a current, native continuous-property
  // subtraction. Imported/manual/model values and counts retain tiny differences.
  const approximate =
    difference !== 0 &&
    continuous.has(key) &&
    data.property_statuses?.[key] === 'comparable' &&
    nativeOrigins.has(data.reference.property_origins[key] ?? '') &&
    data.reference.property_origins[key] === data.candidate.property_origins[key] &&
    typeof first === 'number' &&
    Number.isFinite(first) &&
    typeof second === 'number' &&
    Number.isFinite(second) &&
    second - first === difference &&
    Math.abs(difference) <= 4 * Number.EPSILON * Math.max(1, Math.abs(first), Math.abs(second));
  const sign = difference > 0 ? '+' : '';
  return {
    text: approximate ? '≈ 0' : sign + differenceText(difference, key),
    raw: sign + String(difference),
    approximate,
  };
}
