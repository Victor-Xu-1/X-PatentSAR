import { describe, expect, it, vi } from 'vitest';
import { api, client } from '../src/api';
import { decodeFilterValues } from '../src/api/filterValueDecoders';
import { ContractError } from '../src/api/validation';

const payload = {
  column: 'compound',
  kind: 'text',
  items: [{ value: '8A', count: 2 }],
  total: 1,
  page: 1,
  page_size: 200,
  empty_count: 1,
  matching_rows: 3,
};
const filters = {
  q: 'I & 7',
  confidence: 'unknown',
  review: 'needs_review',
  target: 'A+B',
  page: 4,
  page_size: 25,
  column_filters: [
    { column: 'compound', op: 'not_in' as const, values: ['8'], include_empty: false },
  ],
  sort_column: `activity:${'a'.repeat(64)}`,
  sort_direction: 'desc' as const,
  sort_band: 'strong' as const,
};

describe('filter-values additive v1 boundary', () => {
  it('sends global selectors and own filters to the server, with independent choice pagination and cancellation', async () => {
    const read = vi
      .spyOn(client, 'get')
      .mockImplementation(async (_path, decode) => decode(payload));
    const signal = new AbortController().signal;
    expect(await api.filterValues('project / id', 'compound', filters, '8 & A', 1, signal)).toEqual(
      payload,
    );
    const [path, , receivedSignal] = read.mock.calls[0]!;
    const url = new URL(path, 'http://localhost');
    expect(url.pathname).toBe('/projects/project%20%2F%20id/filter-values');
    expect(url.searchParams.get('column')).toBe('compound');
    expect(url.searchParams.get('search')).toBe('8 & A');
    expect(url.searchParams.get('q')).toBe(filters.q);
    expect(url.searchParams.get('target')).toBe(filters.target);
    expect(url.searchParams.get('confidence')).toBe(filters.confidence);
    expect(url.searchParams.get('review')).toBe(filters.review);
    expect(JSON.parse(url.searchParams.get('column_filters')!)).toEqual(filters.column_filters);
    expect(url.searchParams.get('page')).toBe('1');
    expect(url.searchParams.get('page_size')).toBe('200');
    expect(url.searchParams.has('sort_column')).toBe(false);
    expect(url.searchParams.has('sort_band')).toBe(false);
    expect(receivedSignal).toBe(signal);
  });
  it('validates every bounded field and distinct choices; never exposes presence image URLs', () => {
    expect(decodeFilterValues(payload)).toEqual(payload);
    expect(decodeFilterValues({ ...payload, bands: null })).toEqual(payload);
    expect(
      decodeFilterValues({
        ...payload,
        column: 'structure',
        kind: 'presence',
        items: [],
        total: 0,
      }),
    ).toMatchObject({ kind: 'presence', items: [] });
    for (const patch of [
      { column: '' },
      { column: 'x'.repeat(101) },
      { kind: 'unknown' },
      { items: Array(201).fill(payload.items[0]) },
      { items: [payload.items[0], payload.items[0]] },
      { items: [{ value: '', count: 1 }] },
      { items: [{ value: 'x'.repeat(1001), count: 1 }] },
      { items: [{ value: '8', count: 4 }] },
      { items: [{ value: '8', count: 0 }] },
      { total: 25001 },
      { page: 0 },
      { page: 25001 },
      { page_size: 201 },
      { empty_count: 4 },
      { matching_rows: -1 },
      { matching_rows: 25001 },
      { kind: 'presence' },
      { column: 'structure', kind: 'text' },
      { column: 'property:logP', kind: 'text' },
      { bands: [{ value: 'best', count: 1 }] },
      {
        bands: [
          { value: 'strong', count: 1 },
          { value: 'strong', count: 1 },
        ],
      },
    ])
      expect(() => decodeFilterValues({ ...payload, ...patch })).toThrow(ContractError);
  });
  it('allows ANY-band row counts to overlap, and rejects a mismatched response column/page', async () => {
    expect(
      decodeFilterValues({
        ...payload,
        bands: [
          { value: 'strong', count: 3 },
          { value: 'medium', count: 3 },
        ],
      }).bands,
    ).toHaveLength(2);
    vi.spyOn(client, 'get').mockImplementation(async (_path, decode) =>
      decode({ ...payload, column: 'foreign' }),
    );
    await expect(
      api.filterValues('id', 'compound', filters, '', 1, new AbortController().signal),
    ).rejects.toThrow(ContractError);
    vi.spyOn(client, 'get').mockImplementation(async (_path, decode) =>
      decode({ ...payload, page: 2 }),
    );
    await expect(
      api.filterValues('id', 'compound', filters, '', 1, new AbortController().signal),
    ).rejects.toThrow(ContractError);
  });
  it('rejects out-of-contract search/page requests before transport', () => {
    const read = vi.spyOn(client, 'get');
    for (const [search, page] of [
      ['x'.repeat(501), 1],
      ['', 0],
      ['', 25001],
    ] as const)
      expect(() =>
        api.filterValues('id', 'compound', filters, search, page, new AbortController().signal),
      ).toThrow(ContractError);
    expect(read).not.toHaveBeenCalled();
  });
  it('serializes color sort and blank exclusions identically for results and filtered exports', async () => {
    const read = vi.spyOn(client, 'get').mockResolvedValue({});
    const download = vi.spyOn(client, 'download').mockResolvedValue(new Blob(['contract']));
    await api.results('id', filters, new AbortController().signal);
    await api.export('id', 'csv', [], filters);
    await api.export('id', 'json', [], filters);
    const query = new URL(read.mock.calls[0]![0], 'http://localhost').searchParams;
    expect(query.get('sort_band')).toBe('strong');
    for (const [path] of download.mock.calls) {
      const exported = new URL(path, 'http://localhost').searchParams;
      for (const key of ['column_filters', 'sort_column', 'sort_direction', 'sort_band'])
        expect(exported.get(key)).toBe(query.get(key));
      expect(exported.has('page')).toBe(false);
    }
  });
});
