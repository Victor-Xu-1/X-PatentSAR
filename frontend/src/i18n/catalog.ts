import { common } from './catalogs/common';
import { operations } from './catalogs/operations';
import { workbench } from './catalogs/workbench';

/** One authority with modular ownership; conflicting translations fail the build. */
export function combineCatalogs(
  ...catalogs: Record<string, string>[]
): Readonly<Record<string, string>> {
  const combined: Record<string, string> = Object.create(null);
  for (const catalog of catalogs) {
    for (const [source, english] of Object.entries(catalog)) {
      if (!source || !english || (source in combined && combined[source] !== english))
        throw new Error('Conflicting or empty interface translation');
      combined[source] = english;
    }
  }
  return Object.freeze(combined);
}
export const englishCatalog = combineCatalogs(common, operations, workbench);
