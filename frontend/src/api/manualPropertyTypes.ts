import type { MetricKey } from './predictionTypes';

// Null is an explicit manual blank, not permission to reuse a model value.
export type PropertyOverrides = Partial<Record<MetricKey, number | null>>;
