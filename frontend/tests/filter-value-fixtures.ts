import type { FilterValues } from '../src/api/types';

// Controlled choice API data, deliberately independent of Results / ActivityColumn.
export function filterValuesFixture(
  column: string,
  values = ['A', 'B', 'C'],
  patch: Partial<FilterValues> = {},
): FilterValues {
  return {
    column,
    kind:
      column === 'structure'
        ? 'presence'
        : column.startsWith('property:') || column === 'source'
          ? 'number'
          : 'text',
    items:
      column === 'structure'
        ? []
        : values.map((value, index) => ({ value, count: 3 - (index % 3) })),
    total: column === 'structure' ? 0 : values.length,
    page: 1,
    page_size: 200,
    empty_count: 2,
    matching_rows: 20,
    ...patch,
  };
}
