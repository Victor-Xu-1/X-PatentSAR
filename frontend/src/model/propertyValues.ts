import type { Compound } from '../api/types';
import type { MetricKey } from '../api/predictionTypes';

export function effectiveProperty(row: Compound, key: MetricKey) {
  if (
    !row.correction?.stale &&
    row.property_overrides &&
    Object.hasOwn(row.property_overrides, key)
  )
    return { value: row.property_overrides[key] ?? null, manual: true };
  return {
    value:
      row.admet?.status === 'complete'
        ? (row.admet.properties.find((metric) => metric.key === key)?.value ?? null)
        : null,
    manual: false,
  };
}
