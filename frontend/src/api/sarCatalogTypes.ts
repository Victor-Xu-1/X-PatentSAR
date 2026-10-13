import type {
  StudyFragment,
  StudyOverview,
  StudyRegionSummary,
  StudyReport,
} from './sarStudyTypes';
import type { SARJob } from './sarTypes';

/** Complete membership indexes, not fake empty fragment statistics/structures. */
export type CatalogFragment = Pick<
  StudyFragment,
  'id' | 'molecule_ids' | 'molecule_count' | 'is_reference' | 'representation'
>;
export type CatalogRegion = Omit<StudyRegionSummary, 'fragments'> & {
  fragments: CatalogFragment[];
};
export type CatalogReport = Omit<StudyReport, 'regions'> & { regions: CatalogRegion[] };
export type StudyCatalog = Omit<StudyOverview, 'report'> & { report: CatalogReport };
export interface StudyRegionDetail {
  job: SARJob;
  region: StudyRegionSummary;
  activity_basis: NonNullable<StudyOverview['activity_basis']>;
}
