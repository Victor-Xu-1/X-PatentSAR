import { describe, expect, it } from 'vitest';
import { emptyRoute, parseRoute, routeHash, withoutActivityFocus } from '../src/model/route';
import { readTableQuery, withTableQuery } from '../src/model/tableQueryRoute';
import { compound } from './fixtures';

const queryFor = (criteria: unknown[]) =>
  readTableQuery(new URLSearchParams({ column_filters: JSON.stringify(criteria) }));

const filters = {
  q: '',
  target: '',
  confidence: '',
  review: '',
  page: 3,
  page_size: 25,
  column_filters: [{ column: 'compound', op: 'contains' as const, value: 'Compound 8A & +' }],
  sort_column: 'property:logP',
  sort_direction: 'desc' as const,
};

describe('server column-query state in the existing workspace hash', () => {
  it('round-trips without confusing PDF page, activity focus or project identity', () => {
    const route = withTableQuery(
      {
        ...emptyRoute,
        projectId: 'project-contract',
        page: 79,
        activityFocus: { compoundId: compound.id, key: 'a'.repeat(64) },
      },
      filters,
    );
    const parsed = parseRoute(routeHash(route));
    expect(parsed.tableQuery).toEqual({
      column_filters: filters.column_filters,
      sort_column: filters.sort_column,
      sort_direction: 'desc',
    });
    expect(parsed.page).toBe(79);
    expect(parsed.activityFocus).toEqual(route.activityFocus);
    expect(parsed.projectId).toBe('project-contract');
    expect(withoutActivityFocus(parsed).tableQuery).toEqual(parsed.tableQuery);
  });
  it('removes cleared query state instead of retaining stale filters in the hash', () => {
    const route = withTableQuery({ ...emptyRoute, projectId: 'project-contract' }, filters);
    const clear = withTableQuery(route, { ...filters, column_filters: [], sort_column: '' });
    expect(clear.tableQuery).toBeUndefined();
    expect(routeHash(clear)).not.toMatch(/column_filters|sort_column|sort_direction/);
    expect(route.tableQuery?.column_filters).toEqual(filters.column_filters);
  });
  it('never carries project query state into settings or a projectless page', () => {
    expect(
      withTableQuery({ ...emptyRoute, view: 'settings', tableQuery: filters }, filters).tableQuery,
    ).toBeUndefined();
    expect(
      parseRoute(
        `#/settings?column_filters=${encodeURIComponent(JSON.stringify(filters.column_filters))}&sort_column=compound`,
      ).tableQuery,
    ).toBeUndefined();
  });
  it('bounds and checks URL JSON shape, but leaves unknown-column rejection to the backend', () => {
    for (const input of [
      'not json',
      '{}',
      '[null]',
      '[{"column":"compound","op":"execute"}]',
      'x'.repeat(16_385),
    ])
      expect(readTableQuery(new URLSearchParams({ column_filters: input }))).toBeUndefined();
    const unknown = [{ column: 'future_unknown_column', op: 'eq', value: '1' }];
    expect(
      readTableQuery(new URLSearchParams({ column_filters: JSON.stringify(unknown) }))
        ?.column_filters,
    ).toEqual(unknown);
    expect(
      readTableQuery(new URLSearchParams({ sort_column: 'compound', sort_direction: 'random' })),
    ).toBeUndefined();
  });
});

describe('URL bounds match the published backend query schema', () => {
  it('accepts exactly 16 KiB of UTF-8 JSON and rejects one additional byte', () => {
    const criteria = [{ column: 'compound', op: 'eq', value: '文'.repeat(1000) }];
    const json = JSON.stringify(criteria);
    const raw = json + ' '.repeat(16 * 1024 - new TextEncoder().encode(json).byteLength);
    expect(readTableQuery(new URLSearchParams({ column_filters: raw }))?.column_filters).toEqual(
      criteria,
    );
    expect(readTableQuery(new URLSearchParams({ column_filters: raw + ' ' }))).toBeUndefined();
  });
  it('uses UTF-8 bytes rather than JavaScript character length for multibyte payloads', () => {
    const criteria = Array.from({ length: 7 }, () => ({
      column: 'compound',
      op: 'eq',
      value: '文'.repeat(1000),
    }));
    const json = JSON.stringify(criteria);
    expect(json.length).toBeLessThan(16 * 1024);
    expect(new TextEncoder().encode(json).byteLength).toBeGreaterThan(16 * 1024);
    expect(queryFor(criteria)).toBeUndefined();
  });
  it('accepts 20 criteria and rejects 21 without retaining a partial query', () => {
    const criteria = Array.from({ length: 20 }, () => ({
      column: 'compound',
      op: 'eq',
      value: 'x',
    }));
    expect(queryFor(criteria)?.column_filters).toEqual(criteria);
    expect(queryFor([...criteria, criteria[0]])).toBeUndefined();
  });
  it.each(['x', 'x'.repeat(100), '😀'.repeat(100)])(
    'passes structurally valid unknown column %s to the server',
    (column) => {
      const criteria = [{ column, op: 'eq', value: '1' }];
      expect(queryFor(criteria)?.column_filters).toEqual(criteria);
      expect(readTableQuery(new URLSearchParams({ sort_column: column }))?.sort_column).toBe(
        column,
      );
    },
  );
  it.each(['', 'x'.repeat(101), '😀'.repeat(101)])(
    'rejects empty or oversized column identifiers',
    (column) => {
      expect(queryFor([{ column, op: 'eq', value: '1' }])).toBeUndefined();
      expect(readTableQuery(new URLSearchParams({ sort_column: column }))).toBeUndefined();
    },
  );
  it.each([
    'contains',
    'not_contains',
    'starts_with',
    'ends_with',
    'eq',
    'ne',
    'gt',
    'gte',
    'lt',
    'lte',
  ])('requires a scalar operand for %s and accepts the 1000-character boundary', (op) => {
    for (const operand of [undefined, null, 1, 'x'.repeat(1001)])
      expect(queryFor([{ column: 'compound', op, value: operand }])).toBeUndefined();
    for (const operand of ['', 'x'.repeat(1000), '😀'.repeat(1000)]) {
      const criteria = [{ column: 'compound', op, value: operand }];
      expect(queryFor(criteria)?.column_filters).toEqual(criteria);
    }
  });
  it('requires an in checklist, accepts zero/200 choices and rejects 201 or oversized operands', () => {
    for (const values of [[], Array.from({ length: 200 }, (_, index) => String(index))]) {
      const criteria = [{ column: 'compound', op: 'in', values }];
      expect(queryFor(criteria)?.column_filters).toEqual(criteria);
    }
    for (const values of [undefined, null, 'x', [1], Array(201).fill('x'), ['x'.repeat(1001)]])
      expect(queryFor([{ column: 'compound', op: 'in', values }])).toBeUndefined();
    expect(queryFor([{ column: 'compound', op: 'in', value: 'not a checklist' }])).toBeUndefined();
  });
  it.each(['empty', 'not_empty'])('does not require an operand for %s', (op) => {
    const criteria = [{ column: 'compound', op }];
    expect(queryFor(criteria)?.column_filters).toEqual(criteria);
  });
  it('preserves valid long checkbox values across route serialization and refresh', () => {
    const values = ['long observed value '.repeat(40), '😀'.repeat(1000)];
    const columns = [{ column: 'compound', op: 'in' as const, values }];
    const route = withTableQuery(
      { ...emptyRoute, projectId: 'project-contract' },
      { ...filters, column_filters: columns },
    );
    expect(parseRoute(routeHash(route)).tableQuery?.column_filters).toEqual(columns);
  });
  it('round-trips explicit blank exclusion and activity band sort without stale normal-sort state', () => {
    const columns = [
      { column: 'compound', op: 'not_in' as const, values: ['8A'], include_empty: false },
      { column: `activity:${'a'.repeat(64)}`, op: 'band' as const, value: 'medium' },
    ];
    const route = withTableQuery(
      { ...emptyRoute, projectId: 'id' },
      {
        ...filters,
        column_filters: columns,
        sort_column: `activity:${'a'.repeat(64)}`,
        sort_band: 'none',
      },
    );
    expect(parseRoute(routeHash(route)).tableQuery).toEqual({
      column_filters: columns,
      sort_column: `activity:${'a'.repeat(64)}`,
      sort_direction: 'desc',
      sort_band: 'none',
    });
    const normal = withTableQuery(route, { ...filters, sort_band: '' });
    expect(routeHash(normal)).not.toContain('sort_band');
    expect(
      readTableQuery(new URLSearchParams({ sort_column: 'compound', sort_band: 'strong' }))
        ?.sort_band,
    ).toBeUndefined();
    expect(
      queryFor([{ column: 'compound', op: 'not_in', values: [], include_empty: true }])
        ?.column_filters,
    ).toHaveLength(1);
    expect(
      queryFor([{ column: 'compound', op: 'not_in', values: [], include_empty: 'true' }]),
    ).toBeUndefined();
    expect(
      queryFor([{ column: 'compound', op: 'eq', value: '8', include_empty: true }]),
    ).toBeUndefined();
    expect(queryFor([{ column: 'activity:x', op: 'band', value: 'best' }])).toBeUndefined();
  });
});
