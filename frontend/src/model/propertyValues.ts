import type { Compound } from '../api/types';
import type { MetricKey } from '../api/predictionTypes';

// Producer status is already source/graph/provenance-validated by the API. This
// selector is shared by numeric values and each cell's availability tooltip.
export function propertyObservation(row: Compound, key: MetricKey) {
  const descriptors = key === 'Solubility_AqSolDB' ? null : row.descriptors;
  if (descriptors?.status === 'complete') return descriptors;
  if (row.admet?.status === 'complete') return row.admet;
  return descriptors ?? row.admet ?? null;
}

export function effectiveProperty(row: Compound, key: MetricKey) {
  if (
    !row.correction?.stale &&
    row.property_overrides &&
    Object.hasOwn(row.property_overrides, key)
  )
    return { value: row.property_overrides[key] ?? null, manual: true };
  const observation = propertyObservation(row, key);
  return {
    value:
      observation?.status === 'complete'
        ? (observation.properties.find((metric) => metric.key === key)?.value ?? null)
        : null,
    manual: false,
  };
}
