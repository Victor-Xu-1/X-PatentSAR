import { describe, expect, it, vi } from 'vitest';
import { api, client } from '../src/api';
import { decodeCompound, decodePage } from '../src/api/decoders';
import { emptyRoute, parseRoute, routeHash } from '../src/model/route';
import { compound, page } from './fixtures';

const key = 'a'.repeat(64);
const selection = { compoundId: compound.id, key };
const focus = {
  compound_id: compound.id,
  activity_key: key,
  status: 'located' as const,
  boxes: [[120, 240, 160, 260]],
  message: null,
};
describe('source-bound activity focus contract and refreshable links', () => {
  it('keeps source keys absent on legacy rows and preserves their original observation order', () => {
    expect(decodeCompound(compound)).not.toHaveProperty('activity_source_keys');
    expect(decodeCompound({ ...compound, activity_source_keys: [key] })).toHaveProperty(
      'activity_source_keys',
      [key],
    );
    for (const keys of [[], [key, key], null, ['bad'], ['A'.repeat(64)]])
      expect(() => decodeCompound({ ...compound, activity_source_keys: keys })).toThrow('契约');
  });
  it('retains genuinely rendered focus boxes and truthful page-only responses', () => {
    expect(decodePage(page)).not.toHaveProperty('activity_focus');
    expect(decodePage({ ...page, activity_focus: focus })).toHaveProperty('activity_focus', focus);
    expect(decodePage({ ...page, activity_focus: null }).activity_focus).toBeNull();
    expect(
      decodePage({ ...page, activity_focus: { ...focus, status: 'page_only', boxes: [] } })
        .activity_focus?.status,
    ).toBe('page_only');
  });
  it('rejects more than 2000 source keys even when the observation count matches', () => {
    expect(() =>
      decodeCompound({
        ...compound,
        activities: Array.from({ length: 2_001 }, () => compound.activities[0]!),
        activity_source_keys: Array.from({ length: 2_001 }, () => key),
      }),
    ).toThrow('契约');
  });
  it.each([
    { ...focus, activity_key: 'not-a-hash' },
    { ...focus, compound_id: '' },
    { ...focus, status: 'guessed' },
    { ...focus, boxes: [] },
    { ...focus, status: 'page_only' },
    { ...focus, boxes: Array.from({ length: 81 }, () => [1, 1, 2, 2]) },
    { ...focus, boxes: [[1, 2, 201, 3]] },
    { ...focus, boxes: [[1, 2, 3, 301]] },
    { ...focus, boxes: [[-1, 2, 3, 4]] },
    { ...focus, boxes: [[3, 2, 1, 4]] },
    { ...focus, boxes: [[1, 2, Infinity, 4]] },
    { ...focus, boxes: [[1, 2, 3]] },
  ])('rejects malformed, oversized, nonfinite or unsupported boxes %#', (activity_focus) => {
    expect(() => decodePage({ ...page, activity_focus })).toThrow('契约');
  });
  it('cannot locate a cell without original rendered page dimensions or image', () => {
    for (const fields of [
      { width: null },
      { height: null },
      { width: 0 },
      { height: -1 },
      { image_url: null },
    ])
      expect(() => decodePage({ ...page, ...fields, activity_focus: focus })).toThrow('契约');
  });
  it('preserves the selected observation on refresh and same-page metric changes', () => {
    const route = { ...emptyRoute, projectId: 'project', page: 4, activityFocus: selection };
    expect(parseRoute(routeHash(route))).toEqual(route);
    expect(routeHash(route)).toContain('focusCompound=I-7');
    expect(routeHash(route)).toContain(`focusActivity=${key}`);
    const next = { ...route, activityFocus: { ...selection, key: 'b'.repeat(64) } };
    expect(routeHash(next)).not.toBe(routeHash(route));
    expect(parseRoute(routeHash(next))).toEqual(next);
  });
  it.each([
    `focusCompound=I-7`,
    `focusActivity=${key}`,
    `focusCompound=&focusActivity=${key}`,
    `focusCompound=I-7&focusActivity=bad`,
    `focusCompound=%00I-7&focusActivity=${key}`,
    `focusCompound=${'x'.repeat(201)}&focusActivity=${key}`,
  ])('ignores unpaired or invalid URL focus instead of requesting it: %s', (params) => {
    expect(parseRoute(`#/projects/p?page=4&${params}`)).not.toHaveProperty('activityFocus');
  });
  it('does not serialize invalid selection or selection outside a document page', () => {
    expect(
      routeHash({
        ...emptyRoute,
        projectId: 'p',
        page: 4,
        activityFocus: { compoundId: 'I-7', key: 'bad' },
      }),
    ).not.toContain('focusActivity');
    expect(routeHash({ ...emptyRoute, projectId: 'p', activityFocus: selection })).not.toContain(
      'focusActivity',
    );
    expect(parseRoute(`#/jobs?page=4&focusCompound=I-7&focusActivity=${key}`)).not.toHaveProperty(
      'activityFocus',
    );
  });
  it('reuses the page endpoint with paired encoded selectors and rejects mismatched evidence', async () => {
    const get = vi.spyOn(client, 'get').mockResolvedValue(page);
    const signal = new AbortController().signal;
    await api.page('project', 4, signal, { compoundId: 'I/7 空格', key });
    expect(get.mock.calls[0]?.[0]).toBe(
      `/projects/project/pages/4?focus_compound=I%2F7+%E7%A9%BA%E6%A0%BC&focus_activity=${key}`,
    );
    const decoder = get.mock.calls[0]![1];
    expect(() => decoder({ ...page, activity_focus: focus })).toThrow('契约');
    expect(() => decoder({ ...page, page: 5 })).toThrow('契约');
  });
});
