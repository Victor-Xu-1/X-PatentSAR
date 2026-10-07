export const leadStatuses = [
  'not_run',
  'stale',
  'selected',
  'not_selected',
  'ineligible',
  'unranked',
] as const;

// Research prioritization from the backend, never an experimental Lead claim.
export interface LeadAssessment {
  status: (typeof leadStatuses)[number];
  rank: number | null;
  score: number | null;
  activity_coverage: number;
  components: Record<string, number>;
  reasons: string[];
  warnings: string[];
  scaffold: string | null;
  nearest_similarity: number | null;
  policy_version: '1';
  review_only: true;
}
