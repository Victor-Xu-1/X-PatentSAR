import type { StudyRegionSummary } from '../../../api/sarStudyTypes';

/** Only hide nested automatic views of the exact same accepted source pairs.
 * Manual selections and unique comparisons stay visible. Reports stay intact.
 */
export function compactNetworkSites(sites: StudyRegionSummary[]): StudyRegionSummary[] {
  const prepared = sites.map((site) => ({
    site,
    atoms: new Set(site.region.atom_indices),
    members: [
      ...new Set(
        site.fragments
          .flatMap((fragment) => fragment.molecule_ids)
          .filter((id) => id !== site.region.molecule_id),
      ),
    ]
      .sort()
      .join('\0'),
  }));
  return prepared
    .filter(
      (b) =>
        b.site.origin !== 'single_site' ||
        !prepared.some(
          (a) =>
            a.site.origin === 'single_site' &&
            a.site.region.molecule_id === b.site.region.molecule_id &&
            a.site.region.graph_sha256 === b.site.region.graph_sha256 &&
            a.members === b.members &&
            a.atoms.size < b.atoms.size &&
            [...a.atoms].every((index) => b.atoms.has(index)),
        ),
    )
    .map((item) => item.site);
}
