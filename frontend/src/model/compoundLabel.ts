import type { Compound } from '../api/types';
import { t } from '../i18n';

/** The server owns original-label interpretation; IDs remain stable route/join keys. */
export function compoundLabel(row: Compound): string {
  if (
    row.identifier_label == null &&
    row.record_kind === 'structure_only' &&
    row.flags.includes('unassociated_structure') &&
    row.flags.includes('structure_number_unconfirmed') &&
    !row.correction?.has_changes &&
    /^source-structure:[a-f0-9]{32}(?::\d+)?$/.test(row.id)
  ) {
    const reference = row.structure_id || row.id.split(':').at(-1)!.slice(-8);
    if (row.display_id === `编号待确认 ${reference}`) return `${t('编号待确认')} ${reference}`;
  }
  return row.identifier_label ?? row.display_id;
}
