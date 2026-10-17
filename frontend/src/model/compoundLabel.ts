import type { Compound } from '../api/types';
import { t } from '../i18n';

/** The server owns original-label interpretation; IDs remain stable route/join keys. */
export function compoundLabel(row: Compound, localizeGenerated = true): string {
  const correction = row.correction;
  const literalOverride =
    correction?.identifier_changed === true ||
    (correction?.has_changes && correction.identifier_changed !== false);
  if (
    localizeGenerated &&
    row.identifier_label == null &&
    row.source.source_label == null &&
    row.record_kind === 'structure_only' &&
    row.flags.includes('unassociated_structure') &&
    row.flags.includes('structure_number_unconfirmed') &&
    !literalOverride &&
    /^source-structure:[a-f0-9]{32}(?::\d+)?$/.test(row.id)
  ) {
    const reference = row.structure_id || row.id.split(':').at(-1)!.slice(-8);
    if (row.display_id === `编号待确认 ${reference}`) return `${t('编号待确认')} ${reference}`;
  }
  return row.identifier_label ?? row.display_id;
}
