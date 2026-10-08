import type { Compound } from '../api/types';

/** The server owns original-label interpretation; IDs remain stable route/join keys. */
export function compoundLabel(row: Compound): string {
  return row.identifier_label ?? row.display_id;
}
