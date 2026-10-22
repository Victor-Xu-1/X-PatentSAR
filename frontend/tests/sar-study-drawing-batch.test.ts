import { describe, expect, it, vi } from 'vitest';
import { ApiClient } from '../src/api/client';
import { createSARStudyApi } from '../src/api/sarStudyApi';
import { json, session } from './fixtures';
import { sarDrawing, studyJob } from './sar-fixtures';

type Pending = {
  query: URL;
  signal: AbortSignal;
  finish: (value?: unknown, status?: number) => void;
};
function harness() {
  const requests: Pending[] = [];
  const transport = vi.fn<typeof fetch>((url, init) => {
    const query = new URL(String(url), 'http://localhost');
    if (query.pathname.endsWith('/session')) return Promise.resolve(json(session));
    return new Promise((resolve) => {
      requests.push({
        query,
        signal: init!.signal as AbortSignal,
        finish: (value = envelope(query), status = 200) => resolve(json(value, status)),
      });
    });
  });
  return { requests, api: createSARStudyApi(new ApiClient(transport)) };
}
function envelope(query: URL) {
  const id = query.pathname.split('/').at(-3)!;
  return {
    job: { ...studyJob, id },
    kind: query.searchParams.get('kind'),
    region_id: query.searchParams.get('region_id') ?? '',
    items: query.searchParams.getAll('identifier').map((identifier) => ({
      identifier,
      result: { ...sarDrawing, id: identifier },
      error: null,
    })),
  };
}
const settle = () => new Promise((resolve) => setTimeout(resolve, 0));
const signal = () => new AbortController().signal;

describe('bounded passive study drawing transport', () => {
  it('coalesces 50 same-view images into two GETs of at most 32, without caching results', async () => {
    const { api, requests } = harness();
    const pending = Array.from({ length: 50 }, (_, n) =>
      api.drawing(studyJob.id, 'molecule', `m${n}`, signal()),
    );
    await settle();
    expect(requests).toHaveLength(2);
    expect(requests.map((r) => r.query.searchParams.getAll('identifier').length)).toEqual([32, 18]);
    expect(requests.every((r) => r.query.pathname.endsWith('/study/drawings'))).toBe(true);
    requests.forEach((r) => r.finish());
    expect((await Promise.all(pending)).map((r) => r.id)).toEqual(
      Array.from({ length: 50 }, (_, n) => `m${n}`),
    );
    const again = api.drawing(studyJob.id, 'molecule', 'm0', signal());
    await settle();
    expect(requests).toHaveLength(3);
    requests[2]!.finish();
    await again;
  });
  it('isolates job, kind and region while limiting all batches to two concurrent requests', async () => {
    const { api, requests } = harness();
    const pending = [
      api.drawing(studyJob.id, 'molecule', 'same', signal()),
      api.drawing(studyJob.id, 'fragment', 'same', signal(), 'region1'),
      api.drawing(studyJob.id, 'fragment', 'same', signal(), 'region2'),
      api.drawing('another-job', 'scaffold', 'same', signal()),
    ];
    await settle();
    expect(requests).toHaveLength(2);
    requests[0]!.finish();
    await settle();
    expect(requests).toHaveLength(3);
    requests[1]!.finish();
    await settle();
    expect(requests).toHaveLength(4);
    requests.slice(2).forEach((r) => r.finish());
    expect((await Promise.all(pending)).every((r) => r.id === 'same')).toBe(true);
  });
  it('deduplicates pending selectors but cancelling one subscriber does not cancel another', async () => {
    const { api, requests } = harness();
    const cancelled = new AbortController();
    const first = api.drawing(studyJob.id, 'molecule', 'a', cancelled.signal).catch((e) => e);
    const second = api.drawing(studyJob.id, 'molecule', 'a', signal());
    await settle();
    cancelled.abort();
    expect((await first).name).toBe('AbortError');
    expect(requests[0]!.query.searchParams.getAll('identifier')).toEqual(['a']);
    expect(requests[0]!.signal.aborted).toBe(false);
    requests[0]!.finish();
    expect((await second).id).toBe('a');
  });
  it('skips pre-flush cancellation and aborts abandoned requests without adopting late results', async () => {
    const { api, requests } = harness();
    const before = new AbortController();
    const skipped = api.drawing(studyJob.id, 'molecule', 'skip', before.signal).catch((e) => e);
    before.abort();
    expect((await skipped).name).toBe('AbortError');
    await settle();
    expect(requests).toHaveLength(0);
    const old = new AbortController();
    const abandoned = api.drawing(studyJob.id, 'molecule', 'a', old.signal).catch((e) => e);
    await settle();
    old.abort();
    expect((await abandoned).name).toBe('AbortError');
    expect(requests[0]!.signal.aborted).toBe(true);
    const fresh = api.drawing(studyJob.id, 'molecule', 'a', signal());
    await settle();
    requests[0]!.finish();
    await settle();
    expect(requests).toHaveLength(2);
    requests[1]!.finish();
    expect((await fresh).id).toBe('a');
  });
  it('rejects only a failed item without a fabricated SVG', async () => {
    const { api, requests } = harness();
    const good = api.drawing(studyJob.id, 'molecule', 'a', signal());
    const bad = api.drawing(studyJob.id, 'molecule', 'bad', signal()).catch((e) => e);
    await settle();
    const body = envelope(requests[0]!.query);
    requests[0]!.finish({
      ...body,
      items: [
        body.items[0],
        {
          identifier: 'bad',
          result: null,
          error: { status: 404, code: 'missing', message: 'Not found' },
        },
      ],
    });
    expect((await good).id).toBe('a');
    expect(await bad).toMatchObject({ name: 'ApiError', status: 404, code: 'missing' });
  });
  it.each([
    'job',
    'status',
    'kind',
    'region',
    'keys',
    'nested',
    'both',
    'neither',
    'empty',
    'duplicate',
    'oversized',
  ])('rejects a %s contract mismatch for the entire cohort', async (fault) => {
    const { api, requests } = harness();
    const pending = api.drawing(studyJob.id, 'fragment', 'a', signal(), 'r').catch((e) => e);
    await settle();
    const body = envelope(requests[0]!.query);
    const item = body.items[0]!;
    const faults: Record<string, unknown> = {
      job: { ...body, job: { ...body.job, id: 'wrong' } },
      status: { ...body, job: { ...body.job, status: 'running' } },
      kind: { ...body, kind: 'molecule' },
      region: { ...body, region_id: 'wrong' },
      keys: { ...body, items: [{ ...item, identifier: 'wrong' }] },
      nested: { ...body, items: [{ ...item, result: { ...item.result, id: 'wrong' } }] },
      both: { ...body, items: [{ ...item, error: { status: 422, code: 'bad', message: 'bad' } }] },
      neither: { ...body, items: [{ ...item, result: null }] },
      empty: { ...body, items: [] },
      duplicate: { ...body, items: [item, item] },
      oversized: {
        ...body,
        items: [{ ...item, result: { ...item.result, svg: 'x'.repeat(1024 * 1024 + 1) } }],
      },
    };
    requests[0]!.finish(faults[fault]);
    expect((await pending).name).toBe('ContractError');
    expect(requests).toHaveLength(1);
  });
  it('rejects invalid selectors before session/network access', async () => {
    const { api, requests } = harness();
    for (const id of ['', 'x'.repeat(201)]) {
      await expect(api.drawing(studyJob.id, 'molecule', id, signal())).rejects.toThrow();
    }
    expect(requests).toHaveLength(0);
  });
  it('subdivides only explicit response-budget refusals with strictly smaller batches', async () => {
    const { api, requests } = harness();
    const pending = ['a', 'b', 'c', 'd'].map((id) =>
      api.drawing(studyJob.id, 'molecule', id, signal()),
    );
    await settle();
    requests[0]!.finish({ error: { code: 'sar_drawing_batch_large', message: 'Budget' } }, 413);
    await settle();
    expect(requests.map((r) => r.query.searchParams.getAll('identifier'))).toEqual([
      ['a', 'b', 'c', 'd'],
      ['a', 'b'],
      ['c', 'd'],
    ]);
    requests[1]!.finish();
    requests[2]!.finish();
    expect((await Promise.all(pending)).map((r) => r.id)).toEqual(['a', 'b', 'c', 'd']);
  });
  it.each([
    [413, 'sar_drawing_batch_large'],
    [413, 'other_budget'],
    [409, 'sar_report_changed'],
    [403, 'forbidden'],
  ])('does not replay a singleton or unrelated failure: %s/%s', async (status, code) => {
    const { api, requests } = harness();
    const pending = api.drawing(studyJob.id, 'molecule', 'a', signal()).catch((e) => e);
    await settle();
    requests[0]!.finish({ error: { code, message: 'Refused' } }, status);
    expect(await pending).toMatchObject({ status, code });
    await settle();
    expect(requests).toHaveLength(1);
  });
  it('removes queued cancelled images without sending them after active requests finish', async () => {
    const { api, requests } = harness();
    const controllers = Array.from({ length: 70 }, () => new AbortController());
    const pending = controllers.map((c, n) =>
      api.drawing(studyJob.id, 'molecule', `m${n}`, c.signal).catch((e) => e),
    );
    await settle();
    controllers.slice(64).forEach((c) => c.abort());
    requests.forEach((r) => r.finish());
    const results = await Promise.all(pending);
    expect(results.slice(64).every((r) => r.name === 'AbortError')).toBe(true);
    await settle();
    expect(requests).toHaveLength(2);
  });
  it('retains a sole surviving subscriber when a larger cancelled cohort needs subdivision', async () => {
    const { api, requests } = harness();
    const cancelled = new AbortController();
    const first = api.drawing(studyJob.id, 'molecule', 'a', cancelled.signal).catch((e) => e);
    const second = api.drawing(studyJob.id, 'molecule', 'b', signal());
    await settle();
    cancelled.abort();
    requests[0]!.finish({ error: { code: 'sar_drawing_batch_large', message: 'Budget' } }, 413);
    await settle();
    expect((await first).name).toBe('AbortError');
    expect(requests[1]!.query.searchParams.getAll('identifier')).toEqual(['b']);
    requests[1]!.finish();
    expect((await second).id).toBe('b');
  });
});
