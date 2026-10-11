import type { Region } from '../../../api/sarTypes';

/** Compact diagram aliases only; never rename the recorded region or its atoms. */
export function regionMarker(region: Region, order: number) {
  const explicit = region.name?.match(/^R[0-9]{1,5}(?=$|[\s·:.-])/u)?.[0];
  const marker = explicit ?? 'R' + (order + 1);
  const showAlias = !!region.name && !explicit;
  return {
    marker,
    caption: marker + (region.hydrogen_anchor == null ? '' : ' H'),
    description:
      (showAlias ? marker + ' · ' : '') +
      (region.name ?? marker) +
      (region.hydrogen_anchor == null ? '' : ' · H'),
    showAlias,
  };
}
