import { describe, expect, it, vi } from 'vitest';
import { ApiClient } from '../src/api/client';
import { ApiError } from '../src/api/errors';
import { decodeHealth, decodeProject, decodeProjects, decodeReview } from '../src/api/decoders';
import { boundedResponse } from '../src/api/response';
import { api, client } from '../src/api';
import { health, json, project, session } from './fixtures';

describe('API authentication and writes', () => {
  it('filtered export passes all matching filters but never table pagination', async () => {
    const download = vi.spyOn(client, 'download').mockResolvedValue(new Blob(['contract']));
    await api.export('project-contract', 'json', [], {
      q: 'I-7 & +',
      confidence: 'unknown',
      review: 'needs_review',
      target: '测试靶点',
      page: 3,
      page_size: 10,
    });
    const [path, payload] = download.mock.calls[0]!;
    const url = new URL(path, 'http://localhost');
    expect(url.pathname).toBe('/projects/project-contract/export');
    expect(url.searchParams.get('q')).toBe('I-7 & +');
    expect(url.searchParams.get('target')).toBe('测试靶点');
    expect(url.searchParams.has('page')).toBe(false);
    expect(url.searchParams.has('page_size')).toBe(false);
    expect(payload).toEqual({ format: 'json', compound_ids: [] });
  });
  it('selected and all-row export are explicitly unfiltered', async () => {
    const download = vi.spyOn(client, 'download').mockResolvedValue(new Blob(['contract']));
    await api.export('project-contract', 'csv', ['I-7']);
    await api.export('project-contract', 'csv', []);
    expect(download.mock.calls.map(([path]) => path)).toEqual([
      '/projects/project-contract/export',
      '/projects/project-contract/export',
    ]);
    expect(download.mock.calls[0]![1]).toEqual({ format: 'csv', compound_ids: ['I-7'] });
    expect(download.mock.calls[1]![1]).toEqual({ format: 'csv', compound_ids: [] });
  });
  it('bootstraps once for parallel reads with same-origin cookies', async () => {
    const transport = vi.fn<typeof fetch>(async (url) =>
      json(String(url).endsWith('/session') ? session : { items: [] }),
    );
    const client = new ApiClient(transport);
    await Promise.all([
      client.get('/projects', decodeProjects),
      client.get('/projects', decodeProjects),
    ]);
    expect(transport.mock.calls.filter(([url]) => String(url).endsWith('/session'))).toHaveLength(
      1,
    );
    expect(transport.mock.calls.every(([, init]) => init?.credentials === 'same-origin')).toBe(
      true,
    );
  });
  it('health does not require a session', async () => {
    const transport = vi.fn<typeof fetch>(async () => json(health));
    expect(await new ApiClient(transport).get('/health', decodeHealth)).toEqual(health);
    expect(transport).toHaveBeenCalledOnce();
  });
  it('uses raw PDF bytes and CSRF, not multipart', async () => {
    const transport = vi.fn<typeof fetch>(async (url) =>
      json(String(url).endsWith('/session') ? session : project),
    );
    const client = new ApiClient(transport);
    const file = new File(['%PDF-1.7'], 'file.pdf');
    await client.upload('/projects?filename=file.pdf', file, decodeProject);
    const init = transport.mock.calls[1]![1]!;
    expect(init.body).toBe(file);
    expect(init.headers).toMatchObject({
      'Content-Type': 'application/pdf',
      'X-CSRF-Token': session.csrf_token,
    });
  });
  it('preserves the optimistic revision and reports 409 without retry', async () => {
    const transport = vi.fn<typeof fetch>(async (url) =>
      String(url).endsWith('/session')
        ? json(session)
        : json({ error: { code: 'revision_conflict', message: '记录已更新' } }, 409),
    );
    const client = new ApiClient(transport);
    await expect(
      client.mutate('/projects/id/reviews/I-7', 'PUT', { expected_revision: 3 }, decodeReview),
    ).rejects.toMatchObject({ status: 409, code: 'revision_conflict' });
    expect(transport).toHaveBeenCalledTimes(2);
    expect(JSON.parse(String(transport.mock.calls[1]![1]!.body))).toEqual({ expected_revision: 3 });
  });
  it('never automatically retries an uncertain write', async () => {
    const transport = vi.fn<typeof fetch>(async (url) => {
      if (String(url).endsWith('/session')) return json(session);
      throw new TypeError('offline');
    });
    await expect(
      new ApiClient(transport).mutate('/projects/id/jobs', 'POST', {}, decodeProject),
    ).rejects.toMatchObject({ uncertain: true });
    expect(transport).toHaveBeenCalledTimes(2);
  });
  it('invalidates an expired session but does not resubmit a write', async () => {
    const transport = vi.fn<typeof fetch>(async (url) =>
      String(url).endsWith('/session')
        ? json(session)
        : json({ error: { code: 'unauthorized', message: '会话已过期' } }, 401),
    );
    const client = new ApiClient(transport);
    await expect(
      client.mutate('/projects/id/jobs', 'POST', {}, decodeProject),
    ).rejects.toMatchObject({ status: 401 });
    await client.bootstrap();
    expect(transport.mock.calls.filter(([url]) => String(url).endsWith('/session'))).toHaveLength(
      2,
    );
  });
});
describe('bounded reads and errors', () => {
  it('retries a transient read once with backoff', async () => {
    vi.useFakeTimers();
    const transport = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(json({}, 503))
      .mockResolvedValueOnce(json(health));
    const promise = new ApiClient(transport).get('/health', decodeHealth);
    const assertion = expect(promise).resolves.toEqual(health);
    await vi.advanceTimersByTimeAsync(300);
    await assertion;
    expect(transport).toHaveBeenCalledTimes(2);
  });
  it('does not retry validation errors or render server HTML', async () => {
    const transport = vi.fn<typeof fetch>(
      async () => new Response('<h1>traceback secret</h1>', { status: 422 }),
    );
    await expect(new ApiClient(transport).get('/health', decodeHealth)).rejects.toThrow('HTTP 422');
    expect(transport).toHaveBeenCalledOnce();
  });
  it('rejects success-shaped malformed responses', async () => {
    const transport = vi.fn<typeof fetch>(async () => json({ ready: true }));
    await expect(new ApiClient(transport).get('/health', decodeHealth)).rejects.toThrow('契约');
  });
  it('does not issue an aborted stale request', async () => {
    const transport = vi.fn<typeof fetch>(async () => json(health));
    const controller = new AbortController();
    controller.abort();
    await expect(
      new ApiClient(transport).get('/health', decodeHealth, controller.signal),
    ).rejects.toThrow();
    expect(transport).not.toHaveBeenCalled();
  });
  it('rejects oversized streams and declared lengths', async () => {
    await expect(boundedResponse(new Response('012345'), 4)).rejects.toBeInstanceOf(ApiError);
    await expect(
      boundedResponse(new Response('ok', { headers: { 'Content-Length': '100' } }), 4),
    ).rejects.toThrow('大小限制');
  });
  it('rejects non-download success responses', async () => {
    const transport = vi.fn<typeof fetch>(async (url) =>
      String(url).endsWith('/session')
        ? json(session)
        : new Response('<html>error</html>', { headers: { 'Content-Type': 'text/html' } }),
    );
    await expect(new ApiClient(transport).download('/projects/id/export', {})).rejects.toThrow(
      '导出响应格式',
    );
  });
});
