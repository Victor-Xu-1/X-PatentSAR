import { combineCatalogs } from '../catalogMerge';
import { table } from './table';
import { chemistry } from './chemistry';
import { pdf } from './pdf';
import { evidence } from './evidence';

/** Workbench dictionaries have one pure, conflict-checked assembly path. */
export const workbench = combineCatalogs(table, chemistry, pdf, evidence);
