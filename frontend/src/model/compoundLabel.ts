import type { Compound } from '../api/types';
import { t } from '../i18n';

export function isUnassignedSourceId(id: string): boolean {
  return /^source-structure:[a-f0-9]{32}(?::\d+)?$/.test(id);
}

/** Compact application annotation; the original internal key is never rewritten. */
export function sourceAnnotationLabel(id: string, index: number): string {
  return isUnassignedSourceId(id) ? t('未归属结构 {index}', { index }) : id;
}

/** Recognize only application-owned references, never source/manual identifiers. */
export function generatedCompoundReference(row: Compound): string | null {
  const correction = row.correction;
  const literalOverride =
    correction?.identifier_changed === true ||
    (correction?.has_changes && correction.identifier_changed !== false);
  if (
    row.identifier_label == null &&
    row.source.source_label == null &&
    row.record_kind === 'structure_only' &&
    row.flags.includes('unassociated_structure') &&
    row.flags.includes('structure_number_unconfirmed') &&
    !literalOverride &&
    isUnassignedSourceId(row.id)
  ) {
    const reference = row.structure_id || row.id.split(':').at(-1)!.slice(-8);
    if (row.display_id === `编号待确认 ${reference}`) return reference;
  }
  return null;
}

/** The server owns original-label interpretation; IDs remain stable route/join keys. */
export function compoundLabel(row: Compound, localizeGenerated = true): string {
  const reference = localizeGenerated ? generatedCompoundReference(row) : null;
  if (reference !== null) return `${t('编号待确认')} ${reference}`;
  return row.identifier_label ?? row.display_id;
}
