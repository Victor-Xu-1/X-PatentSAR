import type { CatalogRegion } from '../../../api/sarCatalogTypes';

/** Original accepted changed-fragment memberships; never infer a new match. */
export function networkRowSites(sites: CatalogRegion[], moleculeId: string) {
  const choices = sites.filter(
    (site) =>
      site.region.molecule_id !== moleculeId &&
      site.fragments.some(
        (fragment) => !fragment.is_reference && fragment.molecule_ids.includes(moleculeId),
      ),
  );
  // Presentation only: prefer the smaller already-proved reference footprint.
  // Keep every option and stable ties; authored/legacy ordering stays authoritative.
  if (choices.some((site) => site.origin !== 'single_site')) return choices;
  const footprint = (site: CatalogRegion) =>
    site.region.hydrogen_anchor == null ? site.region.atom_indices.length : 1;
  return choices.sort((a, b) => footprint(a) - footprint(b));
}

/** Only hide nested automatic views of the exact same accepted source pairs.
 * Manual selections and unique comparisons stay visible. Reports stay intact.
 */
export function compactNetworkSites(sites: CatalogRegion[]): CatalogRegion[] {
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
            b.site.region.hydrogen_anchor == null &&
            (a.site.region.hydrogen_anchor != null
              ? b.atoms.has(a.site.region.hydrogen_anchor)
              : a.atoms.size < b.atoms.size && [...a.atoms].every((index) => b.atoms.has(index))),
        ),
    )
    .map((item) => item.site);
}
