import type { CatalogRegion, CatalogReport } from '../../../api/sarCatalogTypes';

import { compactNetworkSites } from './networkSites';

export type CoreOrder = 'alternatives' | 'identifier';
export interface CoreChoice {
  id: string;
  label: string;
  sites: CatalogRegion[];
  compact: CatalogRegion[];
  alternativeCount: number;
}

/** View order of published strict alternatives, never a drug/efficacy score. */
export function coreChoices(report: CatalogReport): CoreChoice[] {
  const groups = new Map<string, { label: string; sites: CatalogRegion[] }>();
  for (const summary of report.regions) {
    const automatic =
      summary.origin === 'single_site' || (report.discovery && summary.origin !== 'manual');
    if (automatic && (!summary.matched || summary.no_variation)) continue;
    const group = groups.get(summary.region.molecule_id) ?? {
      label: summary.reference_label,
      sites: [],
    };
    group.sites.push(summary);
    groups.set(summary.region.molecule_id, group);
  }
  return [...groups.entries()].map(([id, group]) => ({
    id,
    ...group,
    compact: compactNetworkSites(group.sites),
    alternativeCount: new Set(
      group.sites.flatMap((site) =>
        site.fragments
          .filter((fragment) => !fragment.is_reference)
          .flatMap((fragment) => fragment.molecule_ids)
          .filter((member) => member !== id),
      ),
    ).size,
  }));
}

export function orderCores(cores: readonly CoreChoice[], order: CoreOrder): CoreChoice[] {
  return cores.toSorted(
    (a, b) =>
      (order === 'alternatives' ? b.alternativeCount - a.alternativeCount : 0) ||
      a.label.localeCompare(b.label, 'en', { numeric: true }) ||
      a.id.localeCompare(b.id),
  );
}
