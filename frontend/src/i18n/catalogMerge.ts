/** Pure conflict-checked data assembly; no locale, React or application imports. */
export function combineCatalogs(
  ...catalogs: Readonly<Record<string, string>>[]
): Readonly<Record<string, string>> {
  const combined: Record<string, string> = Object.create(null);
  for (const catalog of catalogs) {
    for (const [source, target] of Object.entries(catalog)) {
      if (!source || !target || (source in combined && combined[source] !== target))
        throw new Error('Conflicting or empty interface translation');
      combined[source] = target;
    }
  }
  return Object.freeze(combined);
}
