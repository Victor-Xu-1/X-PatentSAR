import type { ActivityScopeFields } from '../api/activityScopeDecoders';

/** Literal table names and source page only; opaque identities stay out of labels. */
export function activityScopeLabel(value: ActivityScopeFields): string {
  return [value.source_table, value.source_context_page ? `p. ${value.source_context_page}` : null]
    .filter(Boolean)
    .join(' · ');
}
