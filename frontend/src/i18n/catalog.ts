import { common } from './catalogs/common';
import { operations } from './catalogs/operations';
import { workbench } from './catalogs/workbench';
import type { Locale } from './languages';
import { combineCatalogs } from './catalogMerge';
export { combineCatalogs } from './catalogMerge';

/** One authority with modular ownership; competing meanings are rejected. */
export const englishCatalog = combineCatalogs(common, operations, workbench);
/** Chinese is the source-copy locale; every additional locale requires a catalog. */
export const messageCatalogs: Record<Exclude<Locale, 'zh-CN'>, Readonly<Record<string, string>>> = {
  en: englishCatalog,
};
